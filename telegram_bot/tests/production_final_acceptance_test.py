#!/usr/bin/env python3
"""PostAssist V2 — PRODUCTION FINAL ACCEPTANCE (11-BOSQICH, 18 majburiy ssenariy).

Har bir ssenariy DETERMINISTIK (mock DB/Telegram) — tashqi xizmat talab
qilinmaydi. Real PostgreSQL (pgserver yoki *_TEST_DATABASE_URL) topilsa
1/8/16 ssenariylar QO'SHIMCHA ravishda jonli bazada ham tekshiriladi; topilmasa
mock natijasi yakuniy hisoblanadi (SKIP yo'q).

  1)  Stars duplicate payment — 10 parallel, PRO faqat 1 marta
  2)  AI quota race — 20 parallel, limitdan oshmaydi
  3)  DB mock failure → fail-closed (quota / premium / RBAC)
  4)  "5 < 10 & price > 100" HTML formatlash
  5)  Albom timeout → blind retry YO'Q (UNKNOWN_DELIVERY)
  6)  Avto-o'chirish: vaqtinchalik xato → deleted BELGILANMAYDI
  7)  Muddati o'tgan PRO → FREE
  8)  Bir chek 10× parallel tasdiq → PRO faqat 1 marta
  9)  Admin bo'lmagan soxta admin callback → rad
  10) AI: Gemini yiqilsa → Groq
  11) AI: Gemini+Groq yiqilsa → OpenRouter
  12) AI: hammasi yiqilsa → graceful error (crash yo'q)
  13) Scheduler 'processing' restart recovery
  14) Invoice payload / summa manipulyatsiyasi → rad
  15) Self-referral → rad
  16) Promo qayta ishlatish → rad
  17) FloodWait — scheduler barqaror (bloklanmaydi, boshqa kanal davom etadi)
  18) DB pool leak yo'q

Ishga tushirish:
    cd telegram_bot && python tests/production_final_acceptance_test.py
"""
import asyncio
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:PROD_FINAL_ACCEPTANCE_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("AI_PROVIDER_TOTAL_TIMEOUT", "1")

ROOT = Path(__file__).resolve().parent.parent  # telegram_bot/
sys.path.insert(0, str(ROOT))

import database as db  # noqa: E402

ADMIN_ID = 123456789
NON_ADMIN = 555000111
_BASE = 9_100_000_000  # jonli test user_id bazasi

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


def section(title):
    print(f"\n{'=' * 64}\n{title}\n{'=' * 64}")


class _Cur:
    """Scriptlangan kursor: fetchone qatorlari ketma-ket olinadi."""

    def __init__(self, rows=(), rowcount=1):
        self.rows = list(rows)
        self.rowcount = rowcount
        self.queries = []

    def execute(self, q, params=None):
        self.queries.append(" ".join(str(q).split()))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows

    def close(self):
        pass


# ============================================================
# 1) STARS DUPLICATE PAYMENT — 10 PARALLEL
# ============================================================

class _PaymentsLedgerFake:
    """payments.telegram_payment_charge_id UNIQUE + FOR UPDATE emulyatsiyasi."""

    def __init__(self):
        self.charges = set()
        self.grants = 0
        self.lock = threading.Lock()  # FOR UPDATE — tranzaksiyalar navbatda

    @contextmanager
    def transaction(self, commit=True):
        with self.lock:
            yield _PaymentsCursor(self)


class _PaymentsCursor:
    def __init__(self, state):
        self.state = state
        self.row = None
        self.rowcount = 1

    def execute(self, q, params=None):
        s = " ".join(str(q).split()).lower()
        if s.startswith("select 1 from users"):
            self.row = (1,)
        elif s.startswith("insert into payments"):
            charge = params[4]
            if charge in self.state.charges:
                self.row = None
            else:
                self.state.charges.add(charge)
                self.row = (len(self.state.charges),)
        elif s.startswith("update users set plan_type"):
            self.state.grants += 1
            self.rowcount = 1
        else:
            self.row = None

    def fetchone(self):
        return self.row


def test_01_stars_duplicate_parallel():
    section("1) STARS DUPLICATE PAYMENT — 10 parallel (mock)")
    from services import payment_service as ps
    state = _PaymentsLedgerFake()
    uid = 777001
    with patch.object(ps, "transaction", state.transaction):
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(
                lambda _: ps.PaymentService.process_stars_payment(
                    uid, "ch_dup_parallel", 75, f"sub_stars_1m_{uid}", "pro", 30),
                range(10)))
    fresh = [r for r in results if r.get("ok") and not r.get("duplicate")]
    dups = [r for r in results if r.get("ok") and r.get("duplicate")]
    check("10 parallel: PRO aynan 1 marta berildi", state.grants == 1, str(state.grants))
    check("10 parallel: 1 ta yangi, 9 ta duplicate", len(fresh) == 1 and len(dups) == 9,
          f"fresh={len(fresh)} dups={len(dups)}")
    check("ledger'da faqat 1 ta charge", len(state.charges) == 1)


def test_01_live(db_mod):
    print("== 1) LIVE: 10 parallel bir xil charge_id ==")
    from services.payment_service import PaymentService
    uid = _BASE + 1
    charge = f"ch_prod_final_{uid}_{int(time.time())}"
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute("INSERT INTO users (user_id, username, plan_type) VALUES (%s, %s, 'free') "
                    "ON CONFLICT (user_id) DO NOTHING", (uid, f"pf_{uid}"))
        cur.execute("UPDATE users SET plan_type='free', subscription_expires_at=NULL WHERE user_id=%s", (uid,))
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(
            lambda _: PaymentService.process_stars_payment(uid, charge, 75, f"sub_stars_1m_{uid}", "pro", 30),
            range(10)))
    fresh = [r for r in results if r.get("ok") and not r.get("duplicate")]
    with db_mod.db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM payments WHERE telegram_payment_charge_id=%s", (charge,))
        n = int(cur.fetchone()[0])
        cur.execute("SELECT EXTRACT(EPOCH FROM (subscription_expires_at - NOW())) FROM users WHERE user_id=%s", (uid,))
        rem = float(cur.fetchone()[0] or 0)
    check("LIVE: 1 ta yangi to'lov, qolgani duplicate", len(fresh) == 1, str([r.get("duplicate") for r in results]))
    check("LIVE: payments'da 1 qator", n == 1, str(n))
    check("LIVE: obuna ~30 kun (300 emas)", 29.9 * 86400 < rem < 30.2 * 86400, f"{rem / 86400:.2f}")


# ============================================================
# 2) AI QUOTA RACE — 20 PARALLEL
# ============================================================

class _QuotaFake:
    def __init__(self, max_ai=5):
        self.max_ai = max_ai
        self.usage = 0
        self.lock = threading.Lock()

    @contextmanager
    def cursor(self, *a, **kw):
        yield _QuotaCursor(self)


class _QuotaCursor:
    def __init__(self, st):
        self.st = st
        self.row = None

    def execute(self, sql, params=None):
        s = " ".join(sql.lower().split())
        if "last_limit_reset" in s:
            self.row = None
            return
        if s.startswith("select plan_type"):
            with self.st.lock:
                self.row = ("free", self.st.usage)
            return
        if s.startswith("update users set ai_requests_today") and "returning ai_requests_today" in s:
            with self.st.lock:
                if self.st.usage < self.st.max_ai:
                    self.st.usage += 1
                    self.row = (self.st.usage,)
                else:
                    self.row = None
            return
        raise AssertionError(f"Unexpected SQL: {sql}")

    def fetchone(self):
        return self.row


def test_02_ai_quota_race():
    section("2) AI QUOTA RACE — 20 parallel")
    st = _QuotaFake(max_ai=5)
    orig = db.db_cursor
    db.db_cursor = st.cursor
    db._AI_QUOTA_RESERVATIONS.clear()
    try:
        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(lambda _: db.check_ai_limit(777002), range(20)))
    finally:
        db.db_cursor = orig
        db._AI_QUOTA_RESERVATIONS.clear()
    allowed = [r for r in results if r[0]]
    check("20 parallel → faqat 5 ta ruxsat", len(allowed) == 5, str(len(allowed)))
    check("DB usage limitdan oshmadi", st.usage == 5, str(st.usage))
    check("15 tasi rad etildi", len(results) - len(allowed) == 15)


# ============================================================
# 3) DB FAILURE → FAIL-CLOSED
# ============================================================

@contextmanager
def _broken_cursor(*a, **kw):
    raise RuntimeError("pool timeout (mock)")
    yield  # pragma: no cover


def test_03_db_failure_fail_closed():
    section("3) DB MOCK FAILURE → FAIL-CLOSED")
    from services import subscription_service as ss
    from services import rbac_service as rbac
    orig = db.db_cursor
    db.db_cursor = _broken_cursor
    try:
        allowed, _, _ = db.check_ai_limit(777003)
        check("AI quota: DB xatosida ruxsat YO'Q", allowed is False)
    finally:
        db.db_cursor = orig
    with patch.object(ss, "db_cursor", _broken_cursor):
        check("is_premium: DB xatosida False", ss.SubscriptionService.is_premium(777003) is False)
        st = ss.SubscriptionService.get_status(777003)
        check("get_status: DB xatosida free/is_pro=False", st.get("is_pro") is False and st.get("plan_type") == "free")
    with patch.object(db, "db_cursor", _broken_cursor):
        try:
            rbac.invalidate_role_cache(NON_ADMIN)
        except Exception:
            pass
        check("RBAC: DB xatosida oddiy user admin EMAS", rbac.is_admin(NON_ADMIN) is False)
        check("RBAC: DB xatosida ruxsat YO'Q", rbac.has_permission(NON_ADMIN, rbac.PERM_MANAGE_PAYMENTS) is False)
    # SchedulerService claim DB xatosida — istisno emas, False/None
    res = None
    try:
        with patch.object(db, "db_cursor", _broken_cursor):
            res = db.claim_post_delivery(1, -100, "2026-01-01T00:00:00+00:00")
    except Exception as e:
        res = e
    check("claim_post_delivery: DB xatosida istisno YO'Q va claimed emas",
          not isinstance(res, Exception) and not (isinstance(res, dict) and res.get("claimed")), str(res))


# ============================================================
# 4) HTML FORMATLASH
# ============================================================

def test_04_html():
    section("4) HTML: \"5 < 10 & price > 100\"")
    from utils.helpers import safe_html, telegram_html_payload, html_escape
    raw = "5 < 10 & price > 100"
    check("safe_html escape", safe_html(raw) == "5 &lt; 10 &amp; price &gt; 100", safe_html(raw))
    check("html_escape escape", html_escape(raw) == "5 &lt; 10 &amp; price &gt; 100")
    payload, mode = telegram_html_payload(raw)
    check("oddiy matn parse_mode=None (Telegram 400 bermaydi)", payload == raw and mode is None, str((payload, mode)))
    tagged = "<b>5 < 10 & price > 100</b> <script>x</script>"
    check("ruxsatli tag saqlanadi, ichki matn escape",
          safe_html(tagged) == "<b>5 &lt; 10 &amp; price &gt; 100</b> &lt;script&gt;x&lt;/script&gt;", safe_html(tagged))


# ============================================================
# 5) ALBOM TIMEOUT → BLIND RETRY YO'Q
# ============================================================

def _sch():
    import scheduler as sch_mod
    sch_mod._UNPERSISTED_SENT.clear()
    sch_mod._journal_loaded = True
    sch_mod.clear_channel_flood()
    return sch_mod


def _album_post(pid, ch="-1001111"):
    import json
    items = json.dumps([{"type": "photo", "file_id": "A1"}, {"type": "photo", "file_id": "A2"}])
    return (pid, 1, ch, "album", "Albom", items, None, None, False,
            datetime.now(timezone.utc), "none", None, None, None, 0, None)


def test_05_album_timeout():
    section("5) ALBOM TIMEOUT → UNKNOWN_DELIVERY, dublikat YO'Q")
    from telegram.error import TimedOut
    sch = _sch()
    orig_path = sch.SENT_JOURNAL_PATH
    sch.SENT_JOURNAL_PATH = ""
    calls = []
    state = {"delivery": "pending", "post": "pending"}

    async def fake_run_db(fn, *args, **kw):
        name = getattr(fn, "__name__", "")
        calls.append((name, args))
        if name == "claim_post_for_delivery":
            if state["delivery"] == "unknown":
                return {"claimed": False, "unknown": True, "status": "unknown"}
            state["delivery"] = "processing"
            return {"claimed": True, "status": "processing", "attempt_count": 0, "idempotency_key": "k5"}
        if name == "mark_unknown_by_key":
            state["delivery"] = "unknown"
            return True
        if name == "mark_post_status":
            state["post"] = args[1]
            return True
        if name == "is_premium":
            return True
        if name == "get_setting":
            return ""
        if name == "bump_channel_post_count":
            return 1
        if name in ("mark_post_processing", "mark_post_as_sent", "retry_post"):
            return True
        return None

    class _Bot:
        def __init__(self):
            self.groups = 0
            self.msgs = 0

        async def send_media_group(self, chat_id, media, **kw):
            self.groups += 1
            raise TimedOut()

        async def send_message(self, *a, **kw):
            self.msgs += 1
            return SimpleNamespace(message_id=1)

    bot = _Bot()
    orig = sch.db.run_db
    sch.db.run_db = fake_run_db
    try:
        asyncio.run(sch._execute_send(bot, _album_post(501)))
        names = [c[0] for c in calls]
        check("send_media_group 1 marta chaqirildi", bot.groups == 1, str(bot.groups))
        check("retry_post CHAQIRILMADI (blind retry yo'q)", "retry_post" not in names, str(names))
        check("delivery 'unknown' deb belgilandi", "mark_unknown_by_key" in names and state["delivery"] == "unknown")
        check("scheduled_posts 'unknown'", ("mark_post_status", (501, "unknown")) in calls, str(calls[-3:]))
        # Keyingi tick: claim 'unknown' → Telegramga qayta murojaat YO'Q
        asyncio.run(sch._execute_send(bot, _album_post(501)))
        check("keyingi urinishda albom QAYTA yuborilmadi", bot.groups == 1, str(bot.groups))
        check("post statusi 'unknown' bo'lib qoldi", state["post"] == "unknown")
    finally:
        sch.db.run_db = orig
        sch.SENT_JOURNAL_PATH = orig_path
        sch._UNPERSISTED_SENT.clear()

    # Oddiy (albom bo'lmagan) TimedOut — avvalgidek backoff bilan retry (regressiya yo'q)
    calls.clear()

    class _Bot2:
        async def send_message(self, *a, **kw):
            raise TimedOut()

    async def fake_run_db2(fn, *args, **kw):
        name = getattr(fn, "__name__", "")
        calls.append((name, args))
        if name == "claim_post_for_delivery":
            return {"claimed": True, "status": "processing", "attempt_count": 0, "idempotency_key": "k5b"}
        if name == "mark_failed_by_key":
            return {"status": "failed", "backoff_seconds": 30, "attempt_count": 1}
        if name == "is_premium":
            return True
        if name == "get_setting":
            return ""
        if name == "bump_channel_post_count":
            return 1
        return True

    text_post = (502, 1, "-1001111", "text", "Salom", None, None, None, False,
                 datetime.now(timezone.utc), "none", None, None, None, 0, None)
    sch.db.run_db = fake_run_db2
    try:
        asyncio.run(sch._execute_send(_Bot2(), text_post))
    finally:
        sch.db.run_db = orig
    names = [c[0] for c in calls]
    check("matnli post TimedOut → retry_post (idempotent send, xavfsiz)", "retry_post" in names, str(names))
    check("matnli post 'unknown' EMAS", "mark_unknown_by_key" not in names)


# ============================================================
# 6) AVTO-O'CHIRISH: TRANSIENT XATO → deleted BELGILANMAYDI
# ============================================================

def test_06_auto_delete_transient():
    section("6) AVTO-O'CHIRISH: transient xato → deleted=false, retry")
    from telegram.error import NetworkError, BadRequest, RetryAfter
    sch = _sch()
    check("classify: NetworkError → transient", sch.classify_delete_error(NetworkError("x")) == "transient")
    check("classify: RetryAfter → transient", sch.classify_delete_error(RetryAfter(7)) == "transient")
    check("classify: 'message to delete not found' → gone",
          sch.classify_delete_error(BadRequest("Message to delete not found")) == "gone")

    for exc, expect_deleted, label in (
        (NetworkError("conn reset"), False, "NetworkError"),
        (BadRequest("Message to delete not found"), True, "not found"),
        (None, True, "muvaffaqiyat"),
    ):
        calls = []

        async def fake_run_db(fn, *args, **kw):
            calls.append((getattr(fn, "__name__", ""), args))
            if getattr(fn, "__name__", "") == "get_posts_to_delete":
                return [(61, "-1001111", 999)]
            return True

        class _Bot:
            async def delete_message(self, chat_id, message_id):
                if exc is not None:
                    raise exc
                return True

        orig = sch.db.run_db
        sch.db.run_db = fake_run_db
        try:
            asyncio.run(sch.check_and_delete_expired_posts(_Bot()))
        finally:
            sch.db.run_db = orig
        names = [c[0] for c in calls]
        if expect_deleted:
            check(f"{label}: mark_post_as_deleted chaqirildi", "mark_post_as_deleted" in names, str(names))
        else:
            check(f"{label}: mark_post_as_deleted CHAQIRILMADI", "mark_post_as_deleted" not in names, str(names))
            check(f"{label}: defer_post_deletion (retry) rejalashtirildi", "defer_post_deletion" in names, str(names))

    # DB funksiyasi: deleted_at tegilmaydi, faqat delete_at suriladi
    cur = _Cur()

    @contextmanager
    def fake_cursor(*a, **kw):
        yield cur

    with patch.object(db, "db_cursor", fake_cursor):
        ok = db.defer_post_deletion(61, 300)
    check("defer_post_deletion faqat delete_at'ni suradi", ok is True and cur.queries
          and "delete_at = NOW()" in cur.queries[0] and "deleted_at IS NULL" in cur.queries[0]
          and "SET deleted_at" not in cur.queries[0], str(cur.queries))


# ============================================================
# 7) MUDDATI O'TGAN PRO → FREE
# ============================================================

def test_07_expired_pro():
    section("7) MUDDATI O'TGAN PRO → FREE")
    from services import subscription_service as ss
    past = datetime.now(timezone.utc) - timedelta(days=1)
    cur = _Cur(rows=[("pro", past)])

    @contextmanager
    def fake_cursor(*a, **kw):
        yield cur

    with patch.object(ss, "db_cursor", fake_cursor):
        st = ss.SubscriptionService.get_status(777007)
    check("expired PRO → is_pro=False", st.get("is_pro") is False, str(st))
    check("expired PRO → plan_type=free", st.get("plan_type") == "free", str(st))
    check("DB'da plan_type='free' ga tushirildi",
          any("plan_type = 'free'" in q for q in cur.queries), str(cur.queries))

    cur2 = _Cur(rows=[("pro", datetime.now(timezone.utc) + timedelta(days=10))])

    @contextmanager
    def fake_cursor2(*a, **kw):
        yield cur2

    with patch.object(ss, "db_cursor", fake_cursor2):
        st2 = ss.SubscriptionService.get_status(777007)
    check("faol PRO saqlanadi (regressiya yo'q)", st2.get("is_pro") is True and st2.get("remaining_days") >= 9, str(st2))


# ============================================================
# 8) BIR CHEK 10× PARALLEL TASDIQ → PRO 1 MARTA
# ============================================================

class _ReceiptFake:
    def __init__(self):
        self.status = "pending"
        self.grants = 0
        self.ledger = set()
        self.lock = threading.Lock()  # FOR UPDATE

    @contextmanager
    def transaction(self, commit=True):
        with self.lock:
            yield _ReceiptCursor(self)


class _ReceiptCursor:
    def __init__(self, st):
        self.st = st
        self.row = None
        self.rowcount = 1

    def execute(self, q, params=None):
        s = " ".join(str(q).split()).lower()
        if s.startswith("select status, user_id, days_granted"):
            self.row = (self.st.status, 777008, 30, 19000)
        elif s.startswith("update users set plan_type = 'pro'"):
            self.st.grants += 1
        elif s.startswith("update payment_receipts set status = 'approved'"):
            self.st.status = "approved"
        elif s.startswith("insert into payments"):
            key = params[4]
            self.rowcount = 0 if key in self.st.ledger else 1
            self.st.ledger.add(key)
        elif s.startswith("select language_code"):
            self.row = ("uz",)
        else:
            self.row = None

    def fetchone(self):
        return self.row


def test_08_receipt_parallel():
    section("8) BIR CHEK 10× PARALLEL TASDIQ (mock)")
    from services import payment_service as ps
    st = _ReceiptFake()
    with patch.object(ps, "transaction", st.transaction):
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(lambda _: ps.PaymentService._approve_receipt(8, ADMIN_ID), range(10)))
    ok = [r for r in results if r.get("ok")]
    already = [r for r in results if r.get("reason") == "already_approved"]
    check("PRO aynan 1 marta berildi", st.grants == 1, str(st.grants))
    check("1 ta ok, 9 ta already_approved", len(ok) == 1 and len(already) == 9, f"ok={len(ok)} already={len(already)}")
    check("ledger'da 1 ta receipt qatori", len(st.ledger) == 1)


def test_08_live(db_mod):
    print("== 8) LIVE: bir chek 10× parallel ==")
    from services.payment_service import PaymentService
    uid = _BASE + 8
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute("INSERT INTO users (user_id, username, plan_type) VALUES (%s, %s, 'free') "
                    "ON CONFLICT (user_id) DO NOTHING", (uid, f"pf_{uid}"))
        cur.execute("UPDATE users SET plan_type='free', subscription_expires_at=NULL WHERE user_id=%s", (uid,))
        cur.execute("INSERT INTO payment_receipts (user_id, status, days_granted, amount_uzs) "
                    "VALUES (%s, 'pending', 30, 19000) RETURNING id", (uid,))
        rid = int(cur.fetchone()[0])
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(lambda _: PaymentService._approve_receipt(rid, ADMIN_ID), range(10)))
    ok = [r for r in results if r.get("ok")]
    with db_mod.db_cursor() as cur:
        cur.execute("SELECT EXTRACT(EPOCH FROM (subscription_expires_at - NOW())), plan_type FROM users WHERE user_id=%s", (uid,))
        rem, plan = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM payments WHERE telegram_payment_charge_id=%s", (f"receipt:{rid}",))
        ledger = int(cur.fetchone()[0])
    check("LIVE: faqat 1 ta ok", len(ok) == 1, str([r.get("reason") for r in results]))
    check("LIVE: PRO ~30 kun (300 emas)", plan == "pro" and 29.9 * 86400 < float(rem or 0) < 30.2 * 86400, f"{plan} {float(rem or 0) / 86400:.2f}")
    check("LIVE: ledger'da 1 qator", ledger == 1, str(ledger))


# ============================================================
# 9) SOXTA ADMIN CALLBACK → RAD
# ============================================================

def _fake_update(user_id, data, chat_id=None):
    answers = []
    replies = []

    async def answer(*a, **kw):
        answers.append((a, kw))

    async def reply_text(*a, **kw):
        replies.append((a, kw))

    async def edit_message_reply_markup(*a, **kw):
        return None

    async def edit_message_text(*a, **kw):
        return None

    msg = SimpleNamespace(chat_id=chat_id or user_id, message_id=1, reply_text=reply_text,
                          chat=SimpleNamespace(id=chat_id or user_id), caption="", text="",
                          edit_reply_markup=edit_message_reply_markup, edit_text=edit_message_text)
    query = SimpleNamespace(from_user=SimpleNamespace(id=user_id, username="u"), data=data,
                            message=msg, answer=answer,
                            edit_message_reply_markup=edit_message_reply_markup,
                            edit_message_text=edit_message_text)
    upd = SimpleNamespace(callback_query=query, effective_user=query.from_user,
                          effective_chat=msg.chat, effective_message=msg)
    return upd, answers, replies


def test_09_forged_admin_callback():
    section("9) NON-ADMIN SOXTA ADMIN CALLBACK → RAD")
    from services import rbac_service as rbac
    from handlers import payment_receipt as pr
    from handlers import photo_check as pc

    # a) Sof RBAC yordamchilari
    upd, _, _ = _fake_update(NON_ADMIN, "rc_ok:1")
    check("verify_admin_callback: non-admin → False", rbac.verify_admin_callback(upd) is False)
    try:
        rbac.admin_callback_guard(upd, "rc_ok:", 1, rbac.PERM_MANAGE_PAYMENTS)
        raised = None
    except rbac.CallbackTampering as e:
        raised = e
    check("admin_callback_guard: non-admin → CallbackTampering(not_admin)",
          raised is not None and raised.reason == "not_admin", str(raised))
    upd_a, _, _ = _fake_update(ADMIN_ID, "rc_ok:42")
    check("admin (server-side ID) → ruxsat", rbac.admin_callback_guard(upd_a, "rc_ok:", 1, rbac.PERM_MANAGE_PAYMENTS) == [42])
    for bad in ("rc_ok:-1", "rc_ok:1e3", "rc_ok:1:2", "rc_ok:", "rc_ok:abc", "rc_ok: 5", "rc_ok:99999999999999999999999"):
        u, _, _ = _fake_update(ADMIN_ID, bad)
        try:
            rbac.admin_callback_guard(u, "rc_ok:", 1)
            ok = False
        except rbac.CallbackTampering as e:
            ok = e.reason == "bad_payload"
        check(f"buzilgan payload rad: {bad!r}", ok)

    # b) Real handler: chek tasdiqlash — DB'ga UMUMAN murojaat yo'q
    calls = []

    async def spy_run_db(fn, *args, **kw):
        calls.append(getattr(fn, "__name__", ""))
        return {"ok": True, "user_id": 1, "days": 30}

    upd, answers, _ = _fake_update(NON_ADMIN, "rc_ok:1")
    ctx = SimpleNamespace(bot=SimpleNamespace(send_message=None), user_data={})
    with patch.object(pr.db, "run_db", spy_run_db):
        asyncio.run(pr.receipt_admin_callback(upd, ctx))
    check("receipt_admin_callback: non-admin → approve_payment_receipt CHAQIRILMADI",
          "approve_payment_receipt" not in calls and "reject_payment_receipt" not in calls, str(calls))

    # c) Admin, lekin payload soxta (manfiy / qo'shimcha bo'lak) → DB'ga murojaat yo'q
    for bad in ("rc_ok:-7", "rc_ok:7:8"):
        calls.clear()
        upd, _, _ = _fake_update(ADMIN_ID, bad)
        with patch.object(pr.db, "run_db", spy_run_db):
            asyncio.run(pr.receipt_admin_callback(upd, ctx))
        check(f"receipt_admin_callback: admin + soxta payload {bad!r} → DB yozuvi yo'q",
              "approve_payment_receipt" not in calls, str(calls))

    # d) Foto moderatsiya callback'i (boshqa user_id bilan) — non-admin rad
    calls.clear()
    upd, _, _ = _fake_update(NON_ADMIN, f"cph:a:{ADMIN_ID}")
    with patch.object(pc.db, "run_db", spy_run_db):
        try:
            asyncio.run(pc.handle_admin_check_photo_callback(upd, ctx))
        except Exception as e:  # handler crash qilmasligi kerak
            check("photo callback: istisno yo'q", False, repr(e))
    check("photo callback: non-admin → DB yozuvi yo'q",
          not any(n for n in calls if "verif" in n.lower() or "approve" in n.lower() or "set_" in n.lower()), str(calls))


# ============================================================
# 10-12) AI FALLBACK
# ============================================================

class _Stub:
    def __init__(self, name, result=None, exc=None):
        self.name = name
        self.tier = 1
        self.result = result
        self.exc = exc
        self.calls = 0

    def is_available(self):
        return True

    async def complete(self, prompt, system_instruction, params, deadline=None):
        self.calls += 1
        if self.exc:
            raise self.exc
        return dict(self.result)


async def _ai_10_11_12():
    from services.ai_service import AIFallbackService, AIProviderError
    section("10) AI: Gemini yiqilsa → Groq")
    g = _Stub("Gemini", exc=AIProviderError(500, "server error", "Gemini"))
    q = _Stub("Groq", result={"post_text": "Groq ok"})
    o = _Stub("OpenRouter", result={"post_text": "OR ok"})
    res = await AIFallbackService([g, q, o]).generate("p", "s", lang="uz")
    check("Gemini 500 → Groq javob berdi", res.get("provider") == "Groq", str(res))
    check("provider_chain Gemini→Groq", res.get("provider_chain") == ["Gemini", "Groq"], str(res.get("provider_chain")))
    check("OpenRouter chaqirilmadi", o.calls == 0)

    section("11) AI: Gemini+Groq yiqilsa → OpenRouter")
    g = _Stub("Gemini", exc=AIProviderError(429, "rate limit", "Gemini"))
    q = _Stub("Groq", exc=TimeoutError("timeout"))
    o = _Stub("OpenRouter", result={"post_text": "OR ok"})
    res = await AIFallbackService([g, q, o]).generate("p", "s", lang="uz")
    check("OpenRouter javob berdi", res.get("provider") == "OpenRouter", str(res))
    check("provider_chain 3 ta", res.get("provider_chain") == ["Gemini", "Groq", "OpenRouter"], str(res.get("provider_chain")))

    section("12) AI: hammasi yiqilsa → graceful error")
    g = _Stub("Gemini", exc=AIProviderError(429, "rate limit", "Gemini"))
    q = _Stub("Groq", exc=AIProviderError(503, "unavailable", "Groq"))
    o = _Stub("OpenRouter", exc=RuntimeError("boom"))
    try:
        res = await AIFallbackService([g, q, o]).generate("p", "s", lang="uz")
        crashed = None
    except Exception as e:  # pragma: no cover
        res, crashed = {}, e
    check("crash yo'q", crashed is None, repr(crashed))
    check("ai_unavailable=True + error matni", res.get("ai_unavailable") is True and bool(res.get("error")), str(res))
    check("quota_safe=True (kvota sarflanmaydi)", res.get("quota_safe") is True, str(res))


# ============================================================
# 13) SCHEDULER RESTART RECOVERY
# ============================================================

def test_13_restart_recovery():
    section("13) SCHEDULER 'processing' RESTART RECOVERY")
    sch = _sch()
    main_src = (ROOT / "main.py").read_text(encoding="utf-8")
    check("main.py: recover_on_startup birinchi tick'dan OLDIN (init_db'dan keyin) chaqiriladi",
          "await recover_on_startup()" in main_src
          and main_src.index("await recover_on_startup()") < main_src.index("check_and_send_posts,", main_src.index("async def main")))

    class _RecCur(_Cur):
        def __init__(self):
            super().__init__()
            self._rc = []

        def execute(self, q, params=None):
            super().execute(q, params)
            s = self.queries[-1]
            if "SET status = 'posted'" in s:
                self.rowcount = 2
            elif "SET status = 'unknown'" in s:
                self.rowcount = 1
            elif "SET status = 'pending'" in s:
                self.rowcount = 3
                self.rows = [(11,), (12,), (13,)]
            else:
                self.rowcount = 0

    cur = _RecCur()

    @contextmanager
    def fake_cursor(*a, **kw):
        yield cur

    with patch.object(db, "db_cursor", fake_cursor):
        res = db.recover_processing_posts_on_startup(0)
    check("natija: posted=2, unknown=1, requeued=3", res == {"posted": 2, "unknown": 1, "requeued": 3, "error": None}, str(res))
    qs = cur.queries
    i_posted = next(i for i, q in enumerate(qs) if "SET status = 'posted'" in q)
    i_unknown = next(i for i, q in enumerate(qs) if "SET status = 'unknown'" in q)
    i_pending = next(i for i, q in enumerate(qs) if "SET status = 'pending'" in q)
    check("tartib: posted → unknown → pending (yuborilganlar HECH QACHON pending bo'lmaydi)",
          i_posted < i_unknown < i_pending)
    check("posted sharti: sent_message_id / sent_post_messages / delivery 'sent'",
          "sent_message_id IS NOT NULL" in qs[i_posted] and "sent_post_messages" in qs[i_posted]
          and "post_deliveries WHERE status = 'sent'" in qs[i_posted])
    check("pending sharti: faqat sent_message_id IS NULL va sent_post_messages'da yo'q",
          "sent_message_id IS NULL" in qs[i_pending] and "NOT IN (SELECT post_id FROM sent_post_messages)" in qs[i_pending])
    check("requeued postlarning delivery'si 'failed' (darhol qayta claim mumkin)",
          any("UPDATE post_deliveries SET status = 'failed'" in q for q in qs))

    # recover_on_startup → DB funksiyasini 0 soniya bilan chaqiradi; xatoda crash yo'q
    calls = []

    async def fake_run_db(fn, *args, **kw):
        calls.append((getattr(fn, "__name__", ""), args))
        return {"posted": 1, "unknown": 0, "requeued": 0, "error": None}

    orig = sch.db.run_db
    sch.db.run_db = fake_run_db
    try:
        out = asyncio.run(sch.recover_on_startup())
    finally:
        sch.db.run_db = orig
    check("recover_on_startup → recover_processing_posts_on_startup(0)",
          calls and calls[0] == ("recover_processing_posts_on_startup", (0,)), str(calls))
    check("natija qaytdi", out.get("posted") == 1)

    async def boom(fn, *a, **k):
        raise RuntimeError("DB down")
    sch.db.run_db = boom
    try:
        out = asyncio.run(sch.recover_on_startup())
    finally:
        sch.db.run_db = orig
    check("DB yotganda ham crash yo'q ({})", out == {})

    # Crash-simulyatsiya: yuborildi, marker yozilmadi → restartdan keyin qayta YUBORILMAYDI
    sent_state = {"db_down": True, "status": "pending"}
    calls.clear()

    async def fake_run_db2(fn, *args, **kw):
        name = getattr(fn, "__name__", "")
        calls.append((name, args))
        if name == "claim_post_for_delivery":
            return {"claimed": True, "status": "processing", "attempt_count": 0, "idempotency_key": "k13"}
        if name in ("mark_post_as_sent", "mark_post_status", "reschedule_recurring_post"):
            if sent_state["db_down"]:
                raise RuntimeError("DB down")
            if name == "mark_post_as_sent":
                sent_state["status"] = "posted"
            elif name == "mark_post_status":
                sent_state["status"] = args[1]
            return True
        if name == "is_premium":
            return True
        if name == "get_setting":
            return ""
        if name == "bump_channel_post_count":
            return 1
        if name == "get_due_posts":
            # Real DB: faqat 'pending' (restart recovery 'processing' → 'pending'
            # qaytargan deb hisoblaymiz); 'posted' HECH QACHON qaytmaydi.
            if sent_state["status"] == "posted":
                return []
            return [(913, 1, "-100", "text", "Bir marta", None, None, None, False, None,
                     "none", None, None, None, 0, None)]
        return True

    class _Bot:
        def __init__(self):
            self.n = 0

        async def send_message(self, *a, **kw):
            self.n += 1
            return SimpleNamespace(message_id=1)

    async def no_sleep(s):
        return None

    bot = _Bot()
    orig_sleep = sch.asyncio.sleep
    orig_path = sch.SENT_JOURNAL_PATH
    sch.SENT_JOURNAL_PATH = ""
    sch.db.run_db, sch.asyncio.sleep = fake_run_db2, no_sleep
    try:
        asyncio.run(sch.check_and_send_posts(bot))
        check("crash-simulyatsiya: post 1 marta yuborildi, marker kutilmoqda", bot.n == 1 and sch.is_sent_but_unpersisted(913))
        # "restart": recovery uni pending'ga qaytardi deb faraz qilamiz (get_due_posts yana beradi)
        asyncio.run(sch.check_and_send_posts(bot))
        check("restartdan keyin QAYTA YUBORILMADI", bot.n == 1, str(bot.n))
        sent_state["db_down"] = False
        asyncio.run(sch.check_and_send_posts(bot))
        check("DB tiklangach marker yozildi, post baribir 1 marta", bot.n == 1 and not sch.is_sent_but_unpersisted(913))
    finally:
        sch.db.run_db, sch.asyncio.sleep = orig, orig_sleep
        sch.SENT_JOURNAL_PATH = orig_path
        sch._UNPERSISTED_SENT.clear()


# ============================================================
# 14) INVOICE PAYLOAD / SUMMA MANIPULYATSIYASI
# ============================================================

def test_14_invoice_manipulation():
    section("14) INVOICE PAYLOAD / SUMMA MANIPULYATSIYASI → RAD")
    from services.payment_service import PaymentService as P
    uid = 777014
    ok, err = P.validate_payload(f"sub_stars_1m_{uid}", uid, 75, "XTR")
    check("to'g'ri payload qabul", ok and ok["days"] == 30 and err is None, str((ok, err)))
    cases = {
        "summa kamaytirilgan (1 star)": (f"sub_stars_1m_{uid}", uid, 1, "XTR"),
        "summa boshqa tarifniki (175 → 1m)": (f"sub_stars_1m_{uid}", uid, 175, "XTR"),
        "boshqa foydalanuvchi ID'si": (f"sub_stars_1m_{uid + 1}", uid, 75, "XTR"),
        "valyuta USD": (f"sub_stars_1m_{uid}", uid, 75, "USD"),
        "yo'q tarif": (f"sub_stars_99y_{uid}", uid, 75, "XTR"),
        "bo'sh payload": ("", uid, 75, "XTR"),
        "SQL/format inyeksiya": (f"sub_stars_1m_{uid}; DROP TABLE users", uid, 75, "XTR"),
        "1 yillik tarif arzon narxda": (f"sub_stars_1y_{uid}", uid, 75, "XTR"),
    }
    for label, args in cases.items():
        plan, err = P.validate_payload(*args)
        check(f"rad: {label}", plan is None and bool(err), str((plan, err)))
    # process_stars_payment: charge_id bo'sh / kun ≤ 0 → invalid
    r = P.process_stars_payment(uid, "", 75, f"sub_stars_1m_{uid}", "pro", 30)
    check("bo'sh charge_id → invalid_payment", r.get("ok") is False and r.get("reason") == "invalid_payment", str(r))
    r = P.process_stars_payment(uid, "ch", 75, f"sub_stars_1m_{uid}", "pro", 0)
    check("duration 0 → invalid_payment", r.get("ok") is False and r.get("reason") == "invalid_payment", str(r))


# ============================================================
# 15) SELF-REFERRAL
# ============================================================

def test_15_self_referral():
    section("15) SELF-REFERRAL → RAD")
    from services import referral_service as rs
    cur = _Cur(rows=[(777015,)])
    ref, reason = rs.ReferralService.validate_referral(cur, 777015, 777015)
    check("o'z-o'ziga referral → None", ref is None, str((ref, reason)))
    check("sabab: self_referral", reason == rs.REASON_SELF_REFERRAL, str(reason))
    check("DB so'rovi bajarilmadi (erta rad)", cur.queries == [], str(cur.queries))
    cur2 = _Cur(rows=[(777016,)])
    ref, reason = rs.ReferralService.validate_referral(cur2, 777015, "777016")
    check("haqiqiy referrer qabul", ref == 777016 and reason == rs.REASON_OK, str((ref, reason)))
    for bad in ("-5", "abc", None, 0):
        ref, reason = rs.ReferralService.validate_referral(_Cur(), 777015, bad)
        check(f"buzilgan referral {bad!r} → rad", ref is None and reason == rs.REASON_NO_REFERRAL, str(reason))


# ============================================================
# 16) PROMO QAYTA ISHLATISH
# ============================================================

class _PromoFake:
    def __init__(self, max_uses=100):
        self.redeemed = set()
        self.uses = 0
        self.max_uses = max_uses
        self.lock = threading.Lock()

    @contextmanager
    def transaction(self, commit=True):
        with self.lock:
            yield _PromoCursor(self)


class _PromoCursor:
    def __init__(self, st):
        self.st = st
        self.row = None
        self.rowcount = 1

    def execute(self, q, params=None):
        s = " ".join(str(q).split()).lower()
        if s.startswith("select id, plan_type, duration_days"):
            self.row = (1, "pro", 30, self.st.max_uses, self.st.uses, True, None)
        elif s.startswith("insert into promo_redemptions"):
            key = (params[0], params[1])
            if key in self.st.redeemed:
                self.row = None
            else:
                self.st.redeemed.add(key)
                self.row = (len(self.st.redeemed),)
        elif s.startswith("update promo_codes set current_uses"):
            self.st.uses += 1
        else:
            self.row = None

    def fetchone(self):
        return self.row


def test_16_promo_reuse():
    section("16) PROMO QAYTA ISHLATISH → RAD (mock)")
    from services import promo_service as pr
    st = _PromoFake()
    with patch.object(pr, "transaction", st.transaction):
        ok1, m1 = pr.PromoService.redeem_promo(777016, "PROMO16")
        ok2, m2 = pr.PromoService.redeem_promo(777016, "PROMO16")
        with ThreadPoolExecutor(max_workers=10) as pool:
            par = list(pool.map(lambda _: pr.PromoService.redeem_promo(777017, "PROMO16"), range(10)))
    check("birinchi ishlatish OK", ok1 is True, m1)
    check("ikkinchi ishlatish RAD", ok2 is False and "avval" in m2.lower(), m2)
    check("10 parallel bir user → 1 ta OK", sum(1 for ok, _ in par if ok) == 1, str(par))
    check("promo current_uses = 2 (777016 + 777017)", st.uses == 2, str(st.uses))


def test_16_live(db_mod):
    print("== 16) LIVE: promo qayta ishlatish ==")
    from services.promo_service import PromoService
    uid = _BASE + 16
    code = f"PF{int(time.time()) % 100000}"
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute("INSERT INTO users (user_id, username, plan_type) VALUES (%s, %s, 'free') "
                    "ON CONFLICT (user_id) DO NOTHING", (uid, f"pf_{uid}"))
        cur.execute("INSERT INTO promo_codes (code, plan_type, duration_days, max_uses, is_active) "
                    "VALUES (%s, 'pro', 7, 100, TRUE)", (code,))
    ok1, _ = PromoService.redeem_promo(uid, code)
    with ThreadPoolExecutor(max_workers=10) as pool:
        par = list(pool.map(lambda _: PromoService.redeem_promo(uid, code), range(10)))
    with db_mod.db_cursor() as cur:
        cur.execute("SELECT current_uses FROM promo_codes WHERE code=%s", (code,))
        uses = int(cur.fetchone()[0])
    check("LIVE: birinchi OK, 10 parallel qayta → hammasi RAD", ok1 and not any(ok for ok, _ in par), str(par))
    check("LIVE: current_uses = 1", uses == 1, str(uses))


# ============================================================
# 17) FLOODWAIT — SCHEDULER BARQAROR
# ============================================================

def test_17_floodwait_stable():
    section("17) FLOODWAIT — scheduler bloklanmaydi, boshqa kanal davom etadi")
    from telegram.error import RetryAfter
    sch = _sch()
    orig_path = sch.SENT_JOURNAL_PATH
    sch.SENT_JOURNAL_PATH = ""
    calls, sleeps = [], []

    def post(pid, ch):
        return (pid, 1, ch, "text", f"P{pid}", None, None, None, False,
                datetime.now(timezone.utc), "none", None, None, None, 0, None)

    due = [post(171, "-100A"), post(172, "-100A"), post(173, "-100B"), post(174, "-100A")]

    async def fake_run_db(fn, *args, **kw):
        name = getattr(fn, "__name__", "")
        calls.append((name, args))
        if name == "get_due_posts":
            return due
        if name == "claim_post_for_delivery":
            return {"claimed": True, "status": "processing", "attempt_count": 0, "idempotency_key": f"k{args[0]}"}
        if name == "mark_failed_by_key":
            return {"status": "failed", "backoff_seconds": 60, "attempt_count": 1}
        if name == "is_premium":
            return True
        if name == "get_setting":
            return ""
        if name == "bump_channel_post_count":
            return 1
        return True

    async def fake_sleep(sec):
        sleeps.append(float(sec))

    class _Bot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, **kw):
            if str(chat_id) == "-100A":
                raise RetryAfter(60)
            self.sent.append(chat_id)
            return SimpleNamespace(message_id=len(self.sent))

    bot = _Bot()
    orig, orig_sleep = sch.db.run_db, sch.asyncio.sleep
    sch.db.run_db, sch.asyncio.sleep = fake_run_db, fake_sleep
    t0 = time.monotonic()
    try:
        asyncio.run(sch.check_and_send_posts(bot))
    finally:
        sch.db.run_db, sch.asyncio.sleep = orig, orig_sleep
        sch.SENT_JOURNAL_PATH = orig_path
        sch.clear_channel_flood()
        sch._UNPERSISTED_SENT.clear()
    elapsed = time.monotonic() - t0
    retry_ids = [c[1][0] for c in calls if c[0] == "retry_post"]
    check("kanal B posti yuborildi (FloodWait boshqa kanalni to'xtatmadi)", bot.sent == ["-100B"], str(bot.sent))
    check("kanal A: 172 va 174 Telegramga URINILMADI (sovutish), DB'da kechiktirildi",
          set(retry_ids) >= {171, 172, 174}, str(retry_ids))
    check("hech bir inline sleep 5s dan oshmadi (60s FloodWait bo'lsa ham)",
          sleeps and max(sleeps) <= sch.FLOOD_WAIT_INLINE_SLEEP_MAX, str(sleeps))
    check("tick real vaqtda bloklanmadi", elapsed < 5, f"{elapsed:.2f}s")
    check("hech qanday post 'failed' bo'lmadi",
          not any(c[0] == "mark_post_status" and c[1][1] == "failed" for c in calls))
    check("check_and_send_posts istisno tashlamadi (scheduler tirik)", True)


# ============================================================
# 18) DB POOL LEAK YO'Q
# ============================================================

class _FakeConn:
    def __init__(self, pool):
        self.pool = pool
        self.autocommit = False
        self.closed = 0

    def cursor(self):
        return _FakePGCursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.closed = 1


class _FakePGCursor:
    def __init__(self, conn):
        self.conn = conn
        self.row = (1,)
        self.rowcount = 1

    def execute(self, q, params=None):
        if "RAISE" in str(q):
            raise RuntimeError("query failed")
        self.row = (1,)

    def fetchone(self):
        return self.row

    def close(self):
        pass


class _FakePool:
    def __init__(self):
        self.out = 0
        self.got = 0
        self.put = 0
        self.lock = threading.Lock()

    def getconn(self):
        with self.lock:
            self.out += 1
            self.got += 1
        return _FakeConn(self)

    def putconn(self, conn, close=False):
        with self.lock:
            self.out -= 1
            self.put += 1

    def closeall(self):
        pass


def test_18_pool_leak():
    section("18) DB POOL LEAK YO'Q")
    pool = _FakePool()
    orig_get_pool = db._get_pool
    db._reset_pool()
    db._get_pool = lambda: pool
    try:
        sem = db._get_semaphore()
        start = sem._value

        def work(i):
            try:
                with db.db_cursor(commit=(i % 2 == 0)) as cur:
                    if i % 3 == 0:
                        cur.execute("SELECT RAISE")  # so'rov xatosi → rollback
                    else:
                        cur.execute("SELECT 1")
                        cur.fetchone()
            except RuntimeError:
                pass
            # ich-ma-ich tranzaksiya (SAVEPOINT) ham ulanish sizdirmasin
            try:
                with db.db_transaction() as cur:
                    cur.execute("SELECT 1")
                    with db.db_transaction() as inner:
                        inner.execute("SELECT 1")
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(work, range(200)))
        check("barcha ulanishlar pool'ga qaytdi (getconn == putconn)", pool.got == pool.put, f"{pool.got} vs {pool.put}")
        check("pool'dan tashqarida ulanish qolmadi", pool.out == 0, str(pool.out))
        check("semafor boshlang'ich holatga qaytdi", sem._value == start == db.DB_POOL_MAX, f"{sem._value} vs {start}")
        check("ich-ma-ich tranzaksiya qo'shimcha ulanish olmadi", pool.got == 200 * 2, str(pool.got))
    finally:
        db._get_pool = orig_get_pool
        db._reset_pool()

    # Pool holati health uchun
    st = db.get_db_pool_status()
    check("get_db_pool_status dict (used/max/available)", isinstance(st, dict) and "max" in st and "used" in st, str(st))


# ============================================================
# LIVE PG (ixtiyoriy — pgserver / *_TEST_DATABASE_URL)
# ============================================================
_local_server = []


def _live_uri():
    for var in ("FINAL_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "INTEGRITY_TEST_DATABASE_URL"):
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
    import tempfile
    try:
        server = pgserver.get_server(os.path.join(tempfile.gettempdir(), "yordamchi_pg_prod_final"))
    except Exception as e:  # pragma: no cover
        print(f"  (pgserver ishga tushmadi: {e})")
        return None
    _local_server.append(server)
    return server.get_uri()


def _run_live():
    uri = _live_uri()
    if not uri:
        print("\n(LIVE PostgreSQL topilmadi — 1/8/16 mock natijalari yakuniy)")
        return
    section("LIVE PostgreSQL (qo'shimcha tekshiruvlar)")
    db.DATABASE_URL = uri
    os.environ["DATABASE_URL"] = uri
    db._reset_pool()
    try:
        db.init_db()
    except Exception as e:
        print(f"  (init_db xatosi: {e} — LIVE o'tkazildi, mock natijalari yakuniy)")
        return
    try:
        test_01_live(db)
        test_08_live(db)
        test_16_live(db)
    finally:
        db.close_pool()


def main():
    print("PostAssist V2 — PRODUCTION FINAL ACCEPTANCE (18 ssenariy)")
    test_01_stars_duplicate_parallel()
    test_02_ai_quota_race()
    test_03_db_failure_fail_closed()
    test_04_html()
    test_05_album_timeout()
    test_06_auto_delete_transient()
    test_07_expired_pro()
    test_08_receipt_parallel()
    test_09_forged_admin_callback()
    asyncio.run(_ai_10_11_12())
    test_13_restart_recovery()
    test_14_invoice_manipulation()
    test_15_self_referral()
    test_16_promo_reuse()
    test_17_floodwait_stable()
    test_18_pool_leak()
    _run_live()

    print(f"\nJAMI: o'tdi={passed}, xato={failures}, o'tkazib yuborildi={skipped}")
    if failures:
        sys.exit(1)
    print("Barcha production final acceptance testlari muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
