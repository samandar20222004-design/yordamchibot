#!/usr/bin/env python3
"""PostAssist V2 — 3-BOSQICH PRODUCTION ACCEPTANCE SUITE (18 majburiy test).

Har bir test DETERMINISTIK (mock DB/Telegram/HTTP) — tashqi xizmatlar
(PostgreSQL, Telegram, AI provayderlari) TALAB QILINMAYDI. Shu sababli
natija doim PASS/FAIL — SKIPPED hech qachon bo'lmaydi.

Qamrov (topshiriqdagi 18 ssenariy bilan birma-bir):

  TEST 1:  Stars bir xil charge_id bilan 10 parallel so'rov → 1 to'lov,
           1 obuna (payments.telegram_payment_charge_id UNIQUE + FOR UPDATE).
  TEST 2:  Free user AI limitiga 20 parallel so'rov → limit oshmaydi
           (atomik shartli UPDATE + xotira rezervatsiyasi).
  TEST 3:  DB mock failure → qat'iy FAIL-CLOSED (quota/premium/RBAC/claim).
  TEST 4:  "5 < 10 & price > 100" matnli post → Telegram HTML xatosiz.
  TEST 5:  Albom jo'natishda timeout → blind retry YO'Q (UNKNOWN_DELIVERY).
  TEST 6:  Avto-o'chirish vaqtinchalik xatoda noto'g'ri "deleted"
           belgilanmaydi (faqat gone/haqiqiy o'chirishda).
  TEST 7:  Muddati o'tgan PRO avtomatik FREE limitiga tushadi
           (get_status lazy downgrade + check_ai_limit/check_channel_limit
           expiry-aware + downgrade_expired_subscriptions sweep).
  TEST 8:  Bir xil kvitansiya (order_id) 10× parallel approve → PRO 1 marta.
  TEST 9:  Non-admin admin callbackini chaqirsa rad etiladi (server-side
           RBAC: payload emas, from_user.id hal qiladi) + tampered payload.
  TEST 10: OpenRouter free router (openrouter/free + :free discovery)
           model fallback ishlashi (real lokal HTTP mock).
  TEST 11: Gemini ishlamasa Groq, Groq ham ishlamasa OpenRouter fallback.
  TEST 12: Barcha AI provayderlar ishlamasa bot qulamaydi — graceful,
           kvota saqlanadi (quota_safe).
  TEST 13: Scheduler 'processing' postlari restart recovery orqali
           yo'qolmaydi va yuborilgani QAYTA yuborilmaydi.
  TEST 14: Payment invoice payload/summa manipulyatsiyasi rad etiladi
           (validate + precheckout + process_stars_payment).
  TEST 15: O'z referral havolasidan o'zini taklif qilish rad etiladi.
  TEST 16: Bir promo-koddan ikkinchi marta foydalanish rad etiladi
           (10 parallel → 1 OK).
  TEST 17: Telegram FloodWait tushganda scheduler qulamaydi: butun tick
           bloklanmaydi, aynan o'sha kanal kechiktiriladi, boshqa kanal
           davom etadi.
  TEST 18: Parallel so'rovlarda DB connection pool leak bo'lmaydi
           (getconn == putconn, semafor tiklanadi, SAVEPOINT ham).

Ishga tushirish:
    bash tests/run_tests.sh          # yoki
    python3 tests/production_acceptance_suite_test.py
"""
import asyncio
import os
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
# Lokal OpenRouter mock server uchun bo'sh port (TEST 10).
_sock = socket.socket()
_sock.bind(("127.0.0.1", 0))
OR_PORT = _sock.getsockname()[1]
_sock.close()
OR_BASE = f"http://127.0.0.1:{OR_PORT}"

os.environ.setdefault("BOT_TOKEN", "123456:ACCEPTANCE_SUITE_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
# AI zanjiri testlari tez va aniq bo'lishi uchun:
os.environ.setdefault("AI_PROVIDER_TOTAL_TIMEOUT", "2")
os.environ.setdefault("AI_MODEL_DISCOVERY", "1")
os.environ["OPENROUTER_API_KEY"] = "test-or-key"
os.environ["OPENROUTER_ENDPOINT"] = f"{OR_BASE}/openrouter/chat/completions"
os.environ["OPENROUTER_MODELS_ENDPOINT"] = f"{OR_BASE}/openrouter/models"

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

ADMIN_ID = 123456789
NON_ADMIN = 555000111
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
    """Scriptlangan sinxron kursor: fetchone qatorlari ketma-ket olinadi."""

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
# TEST 1: STARS — BIR XIL charge_id, 10 PARALLEL
# ============================================================

class _LedgerFake:
    """payments.telegram_payment_charge_id UNIQUE + SELECT FOR UPDATE emulyatsiyasi."""

    def __init__(self):
        self.charges = set()
        self.grants = 0
        self.lock = threading.Lock()  # FOR UPDATE — tranzaksiyalar navbatda

    @contextmanager
    def transaction(self, commit=True):
        with self.lock:
            yield _LedgerCursor(self)


class _LedgerCursor:
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
                self.row = None          # UNIQUE conflict → duplicate
            else:
                self.state.charges.add(charge)
                self.row = (len(self.state.charges),)
        elif s.startswith("update users set plan_type"):
            self.state.grants += 1       # obuna granti
            self.rowcount = 1
        else:
            self.row = None

    def fetchone(self):
        return self.row

    def close(self):
        pass


def test_01_stars_duplicate_parallel():
    section("TEST 1: Stars bir xil charge_id bilan 10 parallel → 1 to'lov, 1 obuna")
    from services import payment_service as ps

    state = _LedgerFake()
    uid = 777001
    charge = "ch_dup_suite_1"
    with patch.object(ps, "transaction", state.transaction):
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(
                lambda _: ps.PaymentService.process_stars_payment(
                    uid, charge, 75, f"sub_stars_1m_{uid}", "pro", 30),
                range(10)))

    fresh = [r for r in results if r.get("ok") and not r.get("duplicate")]
    dups = [r for r in results if r.get("ok") and r.get("duplicate")]
    check("10 parallel: PRO aynan 1 marta berildi (1 obuna)", state.grants == 1, str(state.grants))
    check("10 parallel: 1 ta yangi to'lov, 9 ta duplicate",
          len(fresh) == 1 and len(dups) == 9, f"fresh={len(fresh)} dups={len(dups)}")
    check("ledger'da faqat 1 ta charge qatori", len(state.charges) == 1, str(state.charges))


# ============================================================
# TEST 2: FREE AI LIMIT — 20 PARALLEL
# ============================================================

class _QuotaFake:
    def __init__(self, plan="free", max_ai=5):
        self.plan = plan
        self.max_ai = max_ai
        self.usage = 0
        self.downgrades = 0
        self.lock = threading.Lock()

    @contextmanager
    def cursor(self, *a, **kw):
        yield _QuotaCursor(self)


class _QuotaCursor:
    def __init__(self, st):
        self.st = st
        self.row = None
        self.rowcount = 1

    def execute(self, sql, params=None):
        s = " ".join(sql.lower().split())
        if "last_limit_reset" in s:
            self.row = None
            return
        if s.startswith("select plan_type") and "from users" in s and "channels" not in s:
            with self.st.lock:
                self.row = (self.st.plan, self.st.usage)
            return
        if "select subscription_expires_at" in s:
            # 3-BOSQICH: expired PRO tekshiruvi — faol obuna (kelajakda tugaydi).
            self.row = (datetime.now(timezone.utc) + timedelta(days=10),)
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

    def fetchall(self):
        return []

    def close(self):
        pass


def test_02_ai_quota_race():
    section("TEST 2: Free user AI limitiga 20 parallel → limit oshmaydi")
    import database as db

    st = _QuotaFake(plan="free", max_ai=db.PLAN_LIMITS["free"]["daily_ai_requests"])
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
    check(f"20 parallel → faqat {st.max_ai} ta ruxsat", len(allowed) == st.max_ai, str(len(allowed)))
    check("DB usage limitdan oshmadi", st.usage == st.max_ai, str(st.usage))
    check(f"qolgan {20 - st.max_ai} tasi rad etildi", len(results) - len(allowed) == 20 - st.max_ai)
    check("limit qiymati FREE_DAILY_AI ga teng",
          all(r[2] == db.PLAN_LIMITS["free"]["daily_ai_requests"] for r in results))


# ============================================================
# TEST 3: DB FAILURE → FAIL-CLOSED
# ============================================================

@contextmanager
def _broken_cursor(*a, **kw):
    raise RuntimeError("pool timeout (mock)")
    yield  # pragma: no cover


def test_03_db_failure_fail_closed():
    section("TEST 3: DB mock failure → strict FAIL-CLOSED (ruxsat bermaslik)")
    from services import subscription_service as ss
    from services import rbac_service as rbac
    import database as db

    orig = db.db_cursor
    db.db_cursor = _broken_cursor
    db._AI_QUOTA_RESERVATIONS.clear()
    try:
        allowed, used, _ = db.check_ai_limit(777003)
        check("AI quota: DB xatosida ruxsat YO'Q (used=-1)", allowed is False and used == -1,
              str((allowed, used)))
    finally:
        db.db_cursor = orig
        db._AI_QUOTA_RESERVATIONS.clear()

    with patch.object(ss, "db_cursor", _broken_cursor):
        check("is_premium: DB xatosida False", ss.SubscriptionService.is_premium(777003) is False)
        st = ss.SubscriptionService.get_status(777003)
        check("get_status: DB xatosida free/is_pro=False",
              st.get("is_pro") is False and st.get("plan_type") == "free", str(st))

    with patch.object(db, "db_cursor", _broken_cursor):
        try:
            rbac.invalidate_role_cache(NON_ADMIN)
        except Exception:
            pass
        check("RBAC: DB xatosida oddiy user admin EMAS", rbac.is_admin(NON_ADMIN) is False)
        check("RBAC: DB xatosida ruxsat YO'Q",
              rbac.has_permission(NON_ADMIN, rbac.PERM_MANAGE_PAYMENTS) is False)

    # Delivery claim DB xatosida — istisno yo'q, claim bo'lmaydi (scheduler xavfsiz)
    res = None
    try:
        with patch.object(db, "db_cursor", _broken_cursor):
            res = db.claim_post_delivery(1, -100, "2026-01-01T00:00:00+00:00")
    except Exception as e:
        res = e
    check("claim_post_delivery: DB xatosida istisno YO'Q va claimed emas",
          not isinstance(res, Exception) and not (isinstance(res, dict) and res.get("claimed")),
          str(res))


# ============================================================
# TEST 4: "5 < 10 & price > 100" → TELEGRAM HTML XATOSIZ
# ============================================================

def test_04_html_special_chars():
    section("TEST 4: \"5 < 10 & price > 100\" matnli post → HTML xatosiz")
    from utils.helpers import safe_html, telegram_html_payload, html_escape
    import scheduler as sch

    raw = "5 < 10 & price > 100"
    check("safe_html escape", safe_html(raw) == "5 &lt; 10 &amp; price &gt; 100", safe_html(raw))
    check("html_escape escape", html_escape(raw) == "5 &lt; 10 &amp; price &gt; 100")
    payload, mode = telegram_html_payload(raw)
    check("oddiy matn parse_mode=None (Telegram 400 bermaydi)",
          payload == raw and mode is None, str((payload, mode)))

    tagged = "<b>5 < 10 & price > 100</b> <script>x</script>"
    check("ruxsatli tag saqlanadi, ichki matn escape",
          safe_html(tagged) == "<b>5 &lt; 10 &amp; price &gt; 100</b> &lt;script&gt;x&lt;/script&gt;",
          safe_html(tagged))

    # End-to-end: scheduler compose → telegram payload (post yuborish yo'li)
    composed = sch.compose_post_text(raw, has_ad_free=True, channel_ad="", brand_text="")
    out, out_mode = telegram_html_payload(composed)
    check("compose_post_text → payload xatosiz (mode to'g'ri)",
          isinstance(out, str) and out_mode in (None, "HTML"), str((out[:60], out_mode)))
    # Telegram 400 kafolati: parse_mode=HTML bo'lsa payload ICHIDA yopilmagan
    # raw '<' bo'lmasligi kerak; parse_mode=None bo'lsa raw matn xavfsiz.
    if out_mode == "HTML":
        html_ok = "<10" not in out and "&lt;" in out
    else:
        html_ok = out == composed
    check("Telegram 400 xato bo'lmaydi (HTML rejimda escape / None rejimda raw)",
          html_ok, str((out[:80], out_mode)))


# ============================================================
# TEST 5: ALBOM TIMEOUT → BLIND RETRY YO'Q
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


def test_05_album_timeout_no_blind_retry():
    section("TEST 5: Albom timeout → dublikat retry QILINMAYDI (UNKNOWN_DELIVERY)")
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
            return {"claimed": True, "status": "processing", "attempt_count": 0,
                    "idempotency_key": "k5"}
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

        async def send_media_group(self, chat_id, media, **kw):
            self.groups += 1
            raise TimedOut()

        async def send_message(self, *a, **kw):
            return SimpleNamespace(message_id=1)

    bot = _Bot()
    orig = sch.db.run_db
    sch.db.run_db = fake_run_db
    try:
        asyncio.run(sch._execute_send(bot, _album_post(501)))
        names = [c[0] for c in calls]
        check("send_media_group aynan 1 marta chaqirildi", bot.groups == 1, str(bot.groups))
        check("retry_post CHAQIRILMADI (blind retry taqiqlandi)",
              "retry_post" not in names, str(names))
        check("delivery 'unknown' (UNKNOWN_DELIVERY) deb belgilandi",
              "mark_unknown_by_key" in names and state["delivery"] == "unknown")
        check("scheduled_posts ham 'unknown'", ("mark_post_status", (501, "unknown")) in calls)
        # Keyingi tick: claim 'unknown' qaytarsa — Telegramga qayta murojaat YO'Q
        asyncio.run(sch._execute_send(bot, _album_post(501)))
        check("keyingi urinishda albom QAYTA yuborilmadi (dublikat yo'q)",
              bot.groups == 1, str(bot.groups))
        check("post statusi 'unknown' bo'lib qoldi", state["post"] == "unknown")
    finally:
        sch.db.run_db = orig
        sch.SENT_JOURNAL_PATH = orig_path
        sch._UNPERSISTED_SENT.clear()

    # Regressiya: oddiy (albom bo'lmagan) TimedOut — avvalgidek backoff bilan retry
    calls.clear()

    class _Bot2:
        async def send_message(self, *a, **kw):
            raise TimedOut()

    async def fake_run_db2(fn, *args, **kw):
        name = getattr(fn, "__name__", "")
        calls.append((name, args))
        if name == "claim_post_for_delivery":
            return {"claimed": True, "status": "processing", "attempt_count": 0,
                    "idempotency_key": "k5b"}
        if name == "mark_failed_by_key":
            return {"status": "failed", "backoff_seconds": 30, "attempt_count": 1}
        if name in ("is_premium",):
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
    check("oddiy matn TimedOut'da retry SAQLANADI (regressiya yo'q)",
          "retry_post" in names and "mark_failed_by_key" in names, str(names))


# ============================================================
# TEST 6: AVTO-O'CHIRISH — TRANSIENT XATODA deleted YO'Q
# ============================================================

def test_06_auto_delete_transient():
    section("TEST 6: Avto-o'chirish vaqtinchalik xatoda 'deleted' BELGILANMAYDI")
    from telegram.error import NetworkError, BadRequest, RetryAfter
    sch = _sch()
    check("classify: NetworkError → transient",
          sch.classify_delete_error(NetworkError("x")) == "transient")
    check("classify: RetryAfter → transient",
          sch.classify_delete_error(RetryAfter(7)) == "transient")
    check("classify: 'message to delete not found' → gone",
          sch.classify_delete_error(BadRequest("Message to delete not found")) == "gone")

    for exc, expect_deleted, label in (
        (NetworkError("conn reset"), False, "NetworkError (transient)"),
        (BadRequest("Message to delete not found"), True, "xabar topilmadi (gone)"),
        (None, True, "muvaffaqiyatli o'chirish"),
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
            check(f"{label}: deleted=true yozildi", "mark_post_as_deleted" in names, str(names))
        else:
            check(f"{label}: mark_post_as_deleted CHAQIRILMADI",
                  "mark_post_as_deleted" not in names, str(names))
            check(f"{label}: o'chirish retry'ga kechiktirildi (defer_post_deletion)",
                  "defer_post_deletion" in names, str(names))

    # DB funksiya kontrakti: deleted_at TEGILMAYDI, faqat delete_at suriladi
    import database as db
    cur = _Cur()

    @contextmanager
    def fake_cursor(*a, **kw):
        yield cur

    with patch.object(db, "db_cursor", fake_cursor):
        ok = db.defer_post_deletion(61, 300)
    check("defer_post_deletion faqat delete_at'ni suradi, deleted_at'ga tegmaydi",
          ok is True and cur.queries and "delete_at = NOW()" in cur.queries[0]
          and "deleted_at IS NULL" in cur.queries[0] and "SET deleted_at" not in cur.queries[0],
          str(cur.queries))


# ============================================================
# TEST 7: MUDDATI O'TGAN PRO → AVTOMATIK FREE
# ============================================================

def test_07_expired_pro_downgrade():
    section("TEST 7: Muddati o'tgan PRO avtomatik FREE limitiga tushadi")
    from services import subscription_service as ss
    import database as db

    past = datetime.now(timezone.utc) - timedelta(days=1)

    # a) Lazy downgrade (SubscriptionService.get_status)
    cur = _Cur(rows=[("pro", past)])

    @contextmanager
    def fake_cursor(*a, **kw):
        yield cur

    with patch.object(ss, "db_cursor", fake_cursor):
        st = ss.SubscriptionService.get_status(777007)
    check("expired PRO → is_pro=False", st.get("is_pro") is False, str(st))
    check("expired PRO → plan_type=free", st.get("plan_type") == "free")
    check("DB'da plan_type='free' ga tushirildi (lazy downgrade)",
          any("plan_type = 'free'" in q for q in cur.queries), str(cur.queries))

    cur2 = _Cur(rows=[("pro", datetime.now(timezone.utc) + timedelta(days=10))])

    @contextmanager
    def fake_cursor2(*a, **kw):
        yield cur2

    with patch.object(ss, "db_cursor", fake_cursor2):
        st2 = ss.SubscriptionService.get_status(777007)
    check("faol PRO saqlanadi (regressiya yo'q)",
          st2.get("is_pro") is True and st2.get("remaining_days") >= 9, str(st2))

    # b) 3-BOSQICH: check_ai_limit ham expiry-aware — expired PRO darhol FREE limitda
    free_max = db.PLAN_LIMITS["free"]["daily_ai_requests"]
    stq = _QuotaFake(plan="pro", max_ai=free_max)
    # _QuotaCursor expiry so'roviga 'expired' javob berishi uchun maxsus kursor:
    class _ExpiredQuotaCursor(_QuotaCursor):
        def execute(self, sql, params=None):
            s = " ".join(sql.lower().split())
            if "select subscription_expires_at" in s:
                self.row = (past,)
                return
            if s.startswith("update users set plan_type"):
                with self.st.lock:
                    self.st.downgrades += 1
                self.row = None
                return
            return super().execute(sql, params)

    class _ExpiredQuotaFake(_QuotaFake):
        @contextmanager
        def cursor(self, *a, **kw):
            yield _ExpiredQuotaCursor(self)

    stq = _ExpiredQuotaFake(plan="pro", max_ai=free_max)
    orig = db.db_cursor
    db.db_cursor = stq.cursor
    db._AI_QUOTA_RESERVATIONS.clear()
    try:
        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(lambda _: db.check_ai_limit(777007), range(20)))
    finally:
        db.db_cursor = orig
        db._AI_QUOTA_RESERVATIONS.clear()
    allowed = [r for r in results if r[0]]
    check("expired PRO: AI limiti FREE miqdorida (PRO limiti EMAS)",
          all(r[2] == free_max for r in results), str({r[2] for r in results}))
    check(f"expired PRO: faqat {free_max} ta so'rov o'tdi", len(allowed) == free_max, str(len(allowed)))
    check("expired PRO: lazy 'free' downgrade yozildi",
          stq.downgrades >= 1, str(stq.downgrades))

    # c) 3-BOSQICH: barcha expired obunalarni sweep qiluvchi funksiya
    sweep_cur = _Cur()
    sweep_cur.rowcount = 7

    @contextmanager
    def fake_cursor3(*a, **kw):
        yield sweep_cur

    with patch.object(db, "db_cursor", fake_cursor3):
        n = db.downgrade_expired_subscriptions()
    check("downgrade_expired_subscriptions: 7 ta user tushirildi", n == 7, str(n))
    check("sweep sharti: plan IN (pro, enterprise) AND expires_at <= NOW()",
          sweep_cur.queries and "plan_type IN ('pro', 'enterprise')" in sweep_cur.queries[0]
          and "subscription_expires_at <= NOW()" in sweep_cur.queries[0], str(sweep_cur.queries))

    # d) Scheduler sweep job'i mavjud va xatosiz ishlaydi
    sch = _sch()
    calls = []

    async def fake_run_db(fn, *args, **kw):
        calls.append(getattr(fn, "__name__", ""))
        return 3

    orig_run = sch.db.run_db
    sch.db.run_db = fake_run_db
    try:
        asyncio.run(sch.subscription_sweep_job())
    finally:
        sch.db.run_db = orig_run
    check("scheduler.subscription_sweep_job → downgrade_expired_subscriptions",
          "downgrade_expired_subscriptions" in calls, str(calls))

    main_src = (ROOT / "main.py").read_text(encoding="utf-8")
    check("main.py: subscription_sweep_job rejalashtirilgan (interval)",
          "subscription_sweep_job" in main_src and "subscription_sweep" in main_src)


# ============================================================
# TEST 8: BIR CHEK (order_id) 10× PARALLEL → PRO 1 MARTA
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

    def close(self):
        pass


def test_08_receipt_parallel_approve():
    section("TEST 8: Bir kvitansiya 10× parallel approve → PRO 1 marta")
    from services import payment_service as ps

    st = _ReceiptFake()
    with patch.object(ps, "transaction", st.transaction):
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(
                lambda _: ps.PaymentService._approve_receipt(8, ADMIN_ID), range(10)))
    ok = [r for r in results if r.get("ok")]
    already = [r for r in results if r.get("reason") == "already_approved"]
    check("PRO aynan 1 marta berildi", st.grants == 1, str(st.grants))
    check("1 ta ok, 9 ta already_approved",
          len(ok) == 1 and len(already) == 9, f"ok={len(ok)} already={len(already)}")
    check("ledger'da 1 ta receipt qatori (receipt:<id> idempotent)", len(st.ledger) == 1)


# ============================================================
# TEST 9: NON-ADMIN SOXTA ADMIN CALLBACK → RAD
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
    section("TEST 9: Non-admin admin callbackini chaqirsa RAD etiladi (RBAC)")
    from services import rbac_service as rbac
    from handlers import payment_receipt as pr

    # a) Sof RBAC yordamchilari — server-side from_user.id hal qiladi
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
    check("haqiqiy admin (server-side ID) → ruxsat",
          rbac.admin_callback_guard(upd_a, "rc_ok:", 1, rbac.PERM_MANAGE_PAYMENTS) == [42])

    # b) ADMIN hatto soxta (tampered) payload yuborsa ham rad
    for bad in ("rc_ok:-1", "rc_ok:1e3", "rc_ok:1:2", "rc_ok:", "rc_ok:abc",
                "rc_ok: 5", "rc_ok:99999999999999999999999"):
        u, _, _ = _fake_update(ADMIN_ID, bad)
        try:
            rbac.admin_callback_guard(u, "rc_ok:", 1)
            ok = False
        except rbac.CallbackTampering as e:
            ok = e.reason == "bad_payload"
        check(f"buzilgan payload rad: {bad!r}", ok)

    # c) Real handler: chek tasdiqlash — non-admin bosanda DB'ga MUmUMON murojaat YO'Q
    calls = []

    async def spy_run_db(fn, *args, **kw):
        calls.append(getattr(fn, "__name__", ""))
        return {"ok": True, "user_id": 1, "days": 30}

    upd, answers, _ = _fake_update(NON_ADMIN, "rc_ok:1")
    ctx = SimpleNamespace(bot=SimpleNamespace(send_message=None), user_data={})
    with patch.object(pr.db, "run_db", spy_run_db):
        asyncio.run(pr.receipt_admin_callback(upd, ctx))
    check("receipt_admin_callback: non-admin → DB amali bajarilmadi", calls == [], str(calls))
    check("receipt_admin_callback: non-admin rad javobi oldi", len(answers) >= 1, str(answers))

    # d) Admin bilan soxta payload — hamon rad (tampering)
    calls.clear()
    upd, _, _ = _fake_update(ADMIN_ID, "rc_ok:abc")
    with patch.object(pr.db, "run_db", spy_run_db):
        asyncio.run(pr.receipt_admin_callback(upd, ctx))
    check("receipt_admin_callback: tampered payload → DB amali bajarilmadi",
          calls == [], str(calls))

    # e) User-side callback data (order_id) manipulyatsiyasi: non-admin hech qanday
    #    admin prefiksidan foydalana olmaydi (guard 'not_admin' — birinchi tekshiruv)
    for data in ("rc_ok:1", "adm_stats", "ad_hub:pool:channel"):
        u, _, _ = _fake_update(NON_ADMIN, data)
        check(f"non-admin soxta admin callback {data!r} → verify False",
              rbac.verify_admin_callback(u) is False)


# ============================================================
# TEST 10: OPENROUTER FREE ROUTER MODEL FALLBACK
# ============================================================

OR_STATE = {
    "models_body": {"data": [
        {"id": "meta-llama/llama-3.3-70b-instruct:free"},
        {"id": "qwen/qwen-2.5-72b-instruct:free"},
        {"id": "google/gemma-2-9b-it:free"},
    ]},
    "decommission_models": set(),  # bu modelarga 400 (decommissioned) qaytadi
    "chat_body": '{"post_text": "OpenRouter post", "scheduled_time": null, '
                 '"has_explicit_time": false, "target_all": false}',
    "chat_requests": [],  # (model) ketma-ketligi
}


async def _or_models_handler(request):
    return _web.json_response(OR_STATE["models_body"])


async def _or_chat_handler(request):
    try:
        body = await request.json()
        model = body.get("model", "?")
    except Exception:
        model = "?"
    OR_STATE["chat_requests"].append(model)
    if model in OR_STATE["decommission_models"]:
        return _web.json_response(
            {"error": {"message": "This model has been decommissioned"}}, status=400)
    return _web.json_response(
        {"choices": [{"message": {"content": OR_STATE["chat_body"]}}]})


async def _start_or_server():
    app = _web.Application()
    app.router.add_get("/openrouter/models", _or_models_handler)
    app.router.add_post("/openrouter/chat/completions", _or_chat_handler)
    runner = _web.AppRunner(app)
    await runner.setup()
    site = _web.TCPSite(runner, "127.0.0.1", OR_PORT)
    await site.start()
    return runner


async def _test_10_async():
    from utils import ai_agent

    runner = await _start_or_server()
    try:
        section("TEST 10: OpenRouter free router model fallback")

        # a) Free router model — zanjirning asosiy (preferred) modeli
        check("OPENROUTER_FREE_ROUTER_MODEL = 'openrouter/free'",
              ai_agent.OPENROUTER_FREE_ROUTER_MODEL == "openrouter/free",
              ai_agent.OPENROUTER_FREE_ROUTER_MODEL)
        check("openrouter/free preferred ro'yxatda birinchi",
              ai_agent.OPENROUTER_MODELS[:1] == ["openrouter/free"],
              str(ai_agent.OPENROUTER_MODELS))

        # b) Discovery: jonli :free modellar topiladi (3-BOSQICH P1 fix —
        #    free-router ID'si ':free' bilan tugamaydi, discovery baribir ishlaydi)
        ai_agent._model_cache.clear()
        models = await ai_agent._discover_openrouter_models("test-or-key")
        check("discovery: jonli :free modellar qaytdi (bo'sh EMAS)",
              isinstance(models, list) and models
              and all(m.endswith(":free") for m in models), str(models))

        # c) E2E: discovery + chat 200 → JSON ajratib olinadi
        ai_agent._model_cache.clear()
        res = await ai_agent._call_openrouter("Salom post yoz", "test-or-key", "sis")
        check("_call_openrouter: javob JSON dict", isinstance(res, dict) and "post_text" in res,
              str(res))
        check("chat so'rovi discovery qilgan :free model bilan ketdi",
              OR_STATE["chat_requests"] and OR_STATE["chat_requests"][0].endswith(":free"),
              str(OR_STATE["chat_requests"]))

        # d) Model fallback: 1-model 400 (decommissioned) → keyingi :free model
        ai_agent._model_cache.clear()
        OR_STATE["chat_requests"].clear()
        OR_STATE["decommission_models"] = {"meta-llama/llama-3.3-70b-instruct:free"}
        try:
            res = await ai_agent._call_openrouter("Salom post yoz", "test-or-key", "sis")
        finally:
            OR_STATE["decommission_models"].clear()
        check("1-model 400 → keyingi modelga o'tildi (model fallback)",
              len(OR_STATE["chat_requests"]) == 2, str(OR_STATE["chat_requests"]))
        check("fallback natijasi qaytdi (bot javob oldi)",
              isinstance(res, dict) and "post_text" in res, str(res))
        check("2-model o'zi :free (free router siyosati)",
              OR_STATE["chat_requests"][-1].endswith(":free")
              or OR_STATE["chat_requests"][-1] == "openrouter/free",
              str(OR_STATE["chat_requests"]))

        # e) Discovery ishlamasa — openrouter/free router zaxira sifatida ishlaydi
        ai_agent._model_cache.clear()
        with patch.object(ai_agent, "_discover_openrouter_models", async_none):
            res = await ai_agent._call_openrouter("p", "test-or-key", "sis")
        check("discovery yo'q → 'openrouter/free' zaxira model ishladi",
              isinstance(res, dict) and OR_STATE["chat_requests"][-1] == "openrouter/free",
              str(OR_STATE["chat_requests"]))
    finally:
        await runner.cleanup()
        try:
            if ai_agent._session and not ai_agent._session.closed:
                await ai_agent._session.close()
        except Exception:
            pass
        ai_agent._session = None


async def async_none(*a, **kw):
    return None


def test_10_openrouter_free_router():
    asyncio.run(_test_10_async())


# ============================================================
# TEST 11-12: AI FALLBACK ZANJIRI
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


async def _test_11_12_async():
    from utils import ai_agent
    from services.ai_service import AIFallbackService, AIProviderError

    section("TEST 11: Gemini ishlamasa → Groq, Groq ham ishlamasa → OpenRouter")
    ai_agent._BREAKERS.clear()

    g = _Stub("Gemini", exc=AIProviderError(500, "server error", "Gemini"))
    q = _Stub("Groq", result={"post_text": "Groq ok"})
    o = _Stub("OpenRouter", result={"post_text": "OR ok"})
    res = await AIFallbackService([g, q, o]).generate("p", "s", lang="uz")
    check("Gemini 500 → Groq javob berdi", res.get("provider") == "Groq", str(res))
    check("provider_chain Gemini→Groq",
          res.get("provider_chain") == ["Gemini", "Groq"], str(res.get("provider_chain")))
    check("OpenRouter chaqirilmadi (kerak bo'lmasa)", o.calls == 0)

    ai_agent._BREAKERS.clear()
    g = _Stub("Gemini", exc=AIProviderError(429, "rate limit", "Gemini"))
    q = _Stub("Groq", exc=TimeoutError("timeout"))
    o = _Stub("OpenRouter", result={"post_text": "OR ok"})
    res = await AIFallbackService([g, q, o]).generate("p", "s", lang="uz")
    check("Gemini+Groq yiqilgan → OpenRouter javob berdi",
          res.get("provider") == "OpenRouter", str(res))
    check("provider_chain 3 ta provayder",
          res.get("provider_chain") == ["Gemini", "Groq", "OpenRouter"],
          str(res.get("provider_chain")))

    section("TEST 12: Barcha AI provayderlar ishlamasa → bot qulamaydi")
    ai_agent._BREAKERS.clear()
    g = _Stub("Gemini", exc=AIProviderError(429, "rate limit", "Gemini"))
    q = _Stub("Groq", exc=AIProviderError(503, "unavailable", "Groq"))
    o = _Stub("OpenRouter", exc=RuntimeError("boom"))
    try:
        res = await AIFallbackService([g, q, o]).generate("p", "s", lang="uz")
        crashed = None
    except Exception as e:  # pragma: no cover
        res, crashed = {}, e
    check("crash YO'Q (istisno tashlanmadi)", crashed is None, repr(crashed))
    check("ai_unavailable=True + xushmuomila error matni",
          res.get("ai_unavailable") is True and bool(res.get("error")), str(res))
    check("quota_safe=True (foydalanuvchi kvotasi yechilmaydi)",
          res.get("quota_safe") is True, str(res))


def test_11_12_ai_fallback_chain():
    asyncio.run(_test_11_12_async())


# ============================================================
# TEST 13: SCHEDULER RESTART RECOVERY
# ============================================================

def test_13_restart_recovery():
    section("TEST 13: Scheduler 'processing' postlari restart recovery bilan saqlanadi")
    sch = _sch()
    main_src = (ROOT / "main.py").read_text(encoding="utf-8")
    check("main.py: recover_on_startup birinchi tick'dan OLDIN chaqiriladi",
          "await recover_on_startup()" in main_src
          and main_src.index("await recover_on_startup()")
          < main_src.index("check_and_send_posts,", main_src.index("async def main")))

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

    import database as db
    with patch.object(db, "db_cursor", fake_cursor):
        res = db.recover_processing_posts_on_startup(0)
    check("natija: posted=2, unknown=1, requeued=3",
          res == {"posted": 2, "unknown": 1, "requeued": 3, "error": None}, str(res))
    qs = cur.queries
    i_posted = next(i for i, q in enumerate(qs) if "SET status = 'posted'" in q)
    i_unknown = next(i for i, q in enumerate(qs) if "SET status = 'unknown'" in q)
    i_pending = next(i for i, q in enumerate(qs) if "SET status = 'pending'" in q)
    check("tartib: posted → unknown → pending (yuborilgan hech qachon pending bo'lmaydi)",
          i_posted < i_unknown < i_pending)
    check("posted sharti: sent_message_id / sent_post_messages / delivery 'sent'",
          "sent_message_id IS NOT NULL" in qs[i_posted]
          and "sent_post_messages" in qs[i_posted]
          and "post_deliveries WHERE status = 'sent'" in qs[i_posted])
    check("pending sharti: faqat isbotlangan yuborilmaganlar",
          "sent_message_id IS NULL" in qs[i_pending]
          and "NOT IN (SELECT post_id FROM sent_post_messages)" in qs[i_pending])
    check("requeued postlarning delivery'si darhol qayta claim qilinadigan bo'ldi",
          any("UPDATE post_deliveries SET status = 'failed'" in q for q in qs))

    # recover_on_startup wrapper: DB funksiyasi 0 soniya bilan chaqiriladi
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

    # Crash-simulyatsiya: yuborildi, marker yozilmadi → restartdan keyin
    # QAYTA YUBORILMAYDI (in-memory guard + keyingi tick'da marker yoziladi)
    sent_state = {"db_down": True, "status": "pending"}
    calls.clear()

    async def fake_run_db2(fn, *args, **kw):
        name = getattr(fn, "__name__", "")
        calls.append((name, args))
        if name == "claim_post_for_delivery":
            return {"claimed": True, "status": "processing", "attempt_count": 0,
                    "idempotency_key": "k13"}
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
        check("crash-simulyatsiya: post 1 marta yuborildi, marker kutilmoqda",
              bot.n == 1 and sch.is_sent_but_unpersisted(913), f"n={bot.n}")
        # "restart": recovery uni pending'ga qaytardi deb faraz (get_due_posts yana beradi)
        asyncio.run(sch.check_and_send_posts(bot))
        check("restartdan keyin QAYTA YUBORILMADI (dublikat yo'q)", bot.n == 1, str(bot.n))
        sent_state["db_down"] = False
        asyncio.run(sch.check_and_send_posts(bot))
        check("DB tiklangach marker yozildi, post baribir 1 marta",
              bot.n == 1 and not sch.is_sent_but_unpersisted(913))
    finally:
        sch.db.run_db, sch.asyncio.sleep = orig, orig_sleep
        sch.SENT_JOURNAL_PATH = orig_path
        sch._UNPERSISTED_SENT.clear()


# ============================================================
# TEST 14: INVOICE PAYLOAD / SUMMA MANIPULYATSIYASI
# ============================================================

def test_14_invoice_manipulation():
    section("TEST 14: Invoice payload/summa manipulyatsiyasi → RAD")
    from services.payment_service import PaymentService as P

    uid = 777014
    ok, err = P.validate_payload(f"sub_stars_1m_{uid}", uid, 75, "XTR")
    check("to'g'ri payload qabul", ok and ok["days"] == 30 and err is None, str((ok, err)))
    cases = {
        "summa kamaytirilgan (1 star)": (f"sub_stars_1m_{uid}", uid, 1, "XTR"),
        "summa boshqa tarifniki": (f"sub_stars_1m_{uid}", uid, 175, "XTR"),
        "boshqa foydalanuvchi ID'si": (f"sub_stars_1m_{uid + 1}", uid, 75, "XTR"),
        "valyuta USD": (f"sub_stars_1m_{uid}", uid, 75, "USD"),
        "yo'q tarif": (f"sub_stars_99y_{uid}", uid, 75, "XTR"),
        "bo'sh payload": ("", uid, 75, "XTR"),
        "SQL/format inyeksiya": (f"sub_stars_1m_{uid}; DROP TABLE users", uid, 75, "XTR"),
    }
    for label, args in cases.items():
        plan, err = P.validate_payload(*args)
        check(f"rad: {label}", plan is None and bool(err), str((plan, err)))

    r = P.process_stars_payment(uid, "", 75, f"sub_stars_1m_{uid}", "pro", 30)
    check("bo'sh charge_id → invalid_payment",
          r.get("ok") is False and r.get("reason") == "invalid_payment", str(r))
    r = P.process_stars_payment(uid, "ch", 75, f"sub_stars_1m_{uid}", "pro", 0)
    check("duration 0 → invalid_payment",
          r.get("ok") is False and r.get("reason") == "invalid_payment", str(r))

    # pre_checkout: Telegram'ga javob ok=False qaytadi (to'lov bo'lmaydi)
    from handlers import subscription as sub

    async def _precheckout(payload, amount, currency, from_user=uid):
        answers = []

        async def answer(*a, **kw):
            answers.append(kw)

        query = SimpleNamespace(
            invoice_payload=payload, total_amount=amount, currency=currency,
            from_user=SimpleNamespace(id=from_user), answer=answer,
        )
        upd = SimpleNamespace(pre_checkout_query=query)
        ctx = SimpleNamespace(user_data={}, bot=None)
        await sub.precheckout_callback(upd, ctx)
        return answers

    answers = asyncio.run(_precheckout(f"sub_stars_1m_{uid}", 1, "XTR"))
    check("precheckout: summa manipulyatsiyasi → ok=False",
          answers and answers[0].get("ok") is False, str(answers))
    answers = asyncio.run(_precheckout(f"sub_stars_1m_{uid + 5}", 75, "XTR"))
    check("precheckout: boshqa user payload'i → ok=False",
          answers and answers[0].get("ok") is False, str(answers))
    answers = asyncio.run(_precheckout(f"sub_stars_1m_{uid}", 75, "XTR"))
    check("precheckout: to'g'ri invoice → ok=True",
          answers and answers[0].get("ok") is True, str(answers))


# ============================================================
# TEST 15: SELF-REFERRAL → RAD
# ============================================================

def test_15_self_referral():
    section("TEST 15: O'z referral havolasidan o'zini taklif qilish → RAD")
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
        check(f"buzilgan referral {bad!r} → rad",
              ref is None and reason == rs.REASON_NO_REFERRAL, str(reason))


# ============================================================
# TEST 16: PROMO QAYTA ISHLATISH → RAD
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

    def close(self):
        pass


def test_16_promo_reuse():
    section("TEST 16: Bir promo-koddan ikkinchi marta foydalanish → RAD")
    from services import promo_service as pr

    st = _PromoFake()
    with patch.object(pr, "transaction", st.transaction):
        ok1, m1 = pr.PromoService.redeem_promo(777016, "PROMO16")
        ok2, m2 = pr.PromoService.redeem_promo(777016, "PROMO16")
        with ThreadPoolExecutor(max_workers=10) as pool:
            par = list(pool.map(lambda _: pr.PromoService.redeem_promo(777017, "PROMO16"),
                                range(10)))
    check("birinchi ishlatish OK", ok1 is True, m1)
    check("ikkinchi ishlatish RAD (allaqachon ishlatilgan)",
          ok2 is False and "avval" in m2.lower(), m2)
    check("10 parallel bir user → 1 ta OK", sum(1 for ok, _ in par if ok) == 1, str(par))
    check("promo current_uses = 2 (har user 1 marta)", st.uses == 2, str(st.uses))


# ============================================================
# TEST 17: FLOODWAIT — SCHEDULER BARQAROR
# ============================================================

def test_17_floodwait_stable():
    section("TEST 17: FloodWait → scheduler qulamaydi, kanal kechiktiriladi")
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
            return {"claimed": True, "status": "processing", "attempt_count": 0,
                    "idempotency_key": f"k{args[0]}"}
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
    check("kanal B posti yuborildi (FloodWait boshqa kanalni to'xtatmadi)",
          bot.sent == ["-100B"], str(bot.sent))
    check("kanal A: 172 va 174 Telegramga URINILMADI (per-kanal sovutish), DB'da kechiktirildi",
          set(retry_ids) >= {171, 172, 174}, str(retry_ids))
    check("hech bir inline sleep 5s dan oshmadi (60s FloodWait bo'lsa ham)",
          sleeps and max(sleeps) <= sch.FLOOD_WAIT_INLINE_SLEEP_MAX, str(sleeps))
    check("tick real vaqtda bloklanmadi", elapsed < 5, f"{elapsed:.2f}s")
    check("hech qanday post 'failed' bo'lmadi",
          not any(c[0] == "mark_post_status" and c[1][1] == "failed" for c in calls))
    check("check_and_send_posts istisno tashlamadi (scheduler tirik)", True)


# ============================================================
# TEST 18: DB CONNECTION POOL LEAK YO'Q
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
    section("TEST 18: Parallel so'rovlarda DB connection pool leak yo'q")
    import database as db

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
            # Ichma-ich tranzaksiya (SAVEPOINT) ham ulanish sizdirmasin
            try:
                with db.db_transaction() as cur:
                    cur.execute("SELECT 1")
                    with db.db_transaction() as inner:
                        inner.execute("SELECT 1")
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(work, range(200)))
        check("barcha ulanishlar pool'ga qaytdi (getconn == putconn)",
              pool.got == pool.put, f"{pool.got} vs {pool.put}")
        check("pool'dan tashqarida ulanish qolmadi", pool.out == 0, str(pool.out))
        check("semafor boshlang'ich holatga qaytdi",
              sem._value == start == db.DB_POOL_MAX, f"{sem._value} vs {start}")
        check("ichma-ich tranzaksiya qo'shimcha ulanish olmadi (SAVEPOINT)",
              pool.got == 200 * 2, str(pool.got))
    finally:
        db._get_pool = orig_get_pool
        db._reset_pool()

    st = db.get_db_pool_status()
    check("get_db_pool_status dict (used/max/available)",
          isinstance(st, dict) and "max" in st and "used" in st, str(st))


# ============================================================
# ASOSIY OQIM
# ============================================================

def main():
    print("PostAssist V2 — 3-BOSQICH PRODUCTION ACCEPTANCE SUITE (18 test)")
    t0 = time.monotonic()
    test_01_stars_duplicate_parallel()
    test_02_ai_quota_race()
    test_03_db_failure_fail_closed()
    test_04_html_special_chars()
    test_05_album_timeout_no_blind_retry()
    test_06_auto_delete_transient()
    test_07_expired_pro_downgrade()
    test_08_receipt_parallel_approve()
    test_09_forged_admin_callback()
    test_10_openrouter_free_router()
    test_11_12_ai_fallback_chain()
    test_13_restart_recovery()
    test_14_invoice_manipulation()
    test_15_self_referral()
    test_16_promo_reuse()
    test_17_floodwait_stable()
    test_18_pool_leak()
    elapsed = time.monotonic() - t0

    print(f"\n{'=' * 64}")
    print(f"JAMI: PASS={passed}, FAIL={failures}, SKIPPED={skipped} ({elapsed:.1f}s)")
    print(f"TESTS: PASS: {passed}, FAIL: {failures}, SKIPPED: {skipped}")
    print(f"{'=' * 64}")
    if failures:
        sys.exit(1)
    print("Barcha 18 ta production acceptance testi muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    # aiohttp web (TEST 10 mock serveri uchun)
    from aiohttp import web as _web
    main()
