#!/usr/bin/env python3
"""🔒 PHASE 2 / 1-QADAM — ATOMIK KVOTA + KREDIT TRANZAKSIYASI (acceptance).

Topshiriq: ``check_ai_limit`` va ``use_user_credit`` alohida tranzaksiyalar
edi → parallel so'rovlarda race condition, DB xatosida esa fail-open xavfi.
Endi ``database.reserve_ai_request()`` kvota/kreditni BITTA tranzaksiyada
(``SELECT ... FOR UPDATE`` + ``credits_ledger`` + ``ai_reservations``) bron
qiladi, ``database.refund_ai_request()`` esa bronni IDEMPOTENT qaytaradi.

Ushbu suite DETERMINISTIK — haqiqiy PostgreSQL/Talab qilinmaydi:
``database.db_transaction`` PostgreSQL qator-qulfi va SAVEPOINT semantikasini
takrorlovchi in-memory dvijok bilan almashtiriladi. Shu sababli
``reserve_ai_request`` / ``refund_ai_request`` ning HAQIQIY kodi (SQL
ketma-ketligi, tranzaksiya chegaralari, fail-closed yo'llari) to'liq
bajariladi — test o'z mantiqining nusxasini emas, mahsulot kodini tekshiradi.

Qamrov:
  TEST 1  Balansda 1 kredit, 5 PARALLEL so'rov → AYNAN 1 ta ruxsat, 4 ta rad
          (race condition yo'q, balans manfiyga tushmaydi).
  TEST 2  Kunlik kvota 3, 5 PARALLEL so'rov → AYNAN 3 ta ruxsat (qator qulfi).
  TEST 3  DB xatosi → qat'iy FAIL-CLOSED (allowed=False, reason=db_error).
  TEST 4  Mablag' yetishmasa → rad ETILADI va bazada HECH QANDAY yarim yozuv
          qolmaydi (bron qatori ham SAVEPOINT'dan qaytadi).
  TEST 5  Kunlik kvota kreditdan AVVAL sarflanadi (source=daily_quota).
  TEST 6  Refund ATOMIK va IDEMPOTENT (2-marta qaytarib bo'lmaydi) — kredit
          va kunlik kvota manbalari uchun.
  TEST 7  Argument validatsiyasi fail-closed (yaroqsiz cost/operation_type).
  TEST 8  services/ai_quota adapteri: haqiqiy DB → atomik yo'l; eski test
          adapteri → legacy zanjir (backward compatibility) + fail-closed.
  TEST 9  Barcha AI oqimlari (Magic Post, AI Studio, Voice, Image, Post
          Score) AYNAN shu transactional funksiyadan foydalanadi va hech
          birida fail-open (``except ... → ruxsat``) qolmagan.

Ishga tushirish:
    bash tests/run_tests.sh          # yoki
    python3 tests/atomic_quota_test.py
"""
import asyncio
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:ATOMIC_QUOTA_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL",
                      "postgresql://user:pass@localhost:5432/testdb")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
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


def section(title):
    print(f"\n{'=' * 64}\n{title}\n{'=' * 64}")


# ---------------------------------------------------------------------------
# IN-MEMORY POSTGRESQL DVIJOK (qator qulfi + SAVEPOINT + tranzaksiya)
# ---------------------------------------------------------------------------
class FakePG:
    """``database.db_transaction`` o'rnini bosuvchi in-memory dvijok.

    * har bir tranzaksiya GLOBAL qulfni ushlaydi — PostgreSQL'ning
      ``SELECT ... FOR UPDATE`` qator qulfi parallel bronlarni
      ketma-ketlashtiradi, shu xatti-harakat takrorlanadi;
    * ich-ma-ich tranzaksiya SAVEPOINT ochadi (xatoda faqat ichki blok
      qaytadi) — ``database._Transaction`` bilan bir xil semantika;
    * COMMIT'da o'zgarishlar asosiy holatga qo'shiladi, ROLLBACK'da
      butunlay tashlanadi (yarim yozuv qolmaydi).
    """

    def __init__(self):
        self.lock = threading.Lock()
        # user_id → {"plan": str, "used": int, "credits": int,
        #            "expires": datetime | None, "reset": date}
        self.users = {}
        # ai_reservations qatorlari: id → dict
        self.reservations = {}
        # credits_ledger qatorlari (doimiy audit)
        self.ledger = []
        self._res_seq = 0
        self._ledger_seq = 0
        # Faol ildiz tranzaksiya holati (SAVEPOINT stack'i uchun).
        self._root = None
        self.savepoints = 0

    # ---- test yordamchilari -------------------------------------------
    def add_user(self, user_id, plan="free", used=0, credits=0, expires=None):
        self.users[int(user_id)] = {
            "plan": plan,
            "used": int(used),
            "credits": int(credits),
            "expires": expires,
            "reset": datetime.now(timezone.utc).date(),
        }

    def snapshot(self, user_id):
        u = self.users.get(int(user_id))
        if not u:
            return None
        return {"plan": u["plan"], "used": u["used"], "credits": u["credits"]}

    def active_reservations(self, user_id=None):
        rows = [r for r in self.reservations.values() if r["status"] == "active"]
        if user_id is not None:
            rows = [r for r in rows if r["user_id"] == int(user_id)]
        return rows

    def _clone(self):
        return {
            "users": {k: dict(v) for k, v in self.users.items()},
            "reservations": {k: dict(v) for k, v in self.reservations.items()},
            "ledger": list(self.ledger),
            "_res_seq": self._res_seq,
            "_ledger_seq": self._ledger_seq,
        }

    def _restore(self, snap):
        self.users = {k: dict(v) for k, v in snap["users"].items()}
        self.reservations = {k: dict(v) for k, v in snap["reservations"].items()}
        self.ledger = list(snap["ledger"])
        self._res_seq = snap["_res_seq"]
        self._ledger_seq = snap["_ledger_seq"]

    # ---- tranzaksiya bloki --------------------------------------------
    @contextmanager
    def tx(self, commit=True, isolation_level=None, readonly=False):
        """``database._Transaction`` semantikasini takrorlaydi.

        * ILDIZ tranzaksiya global qulfni OLADI va snapshot'ni shundan
          KEYIN oladi — PostgreSQL'da parallel tranzaksiyalar commit
          qilingan holatni ko'radi (aks holda ikkinchi tranzaksiya birinchi
          natijasini o'chirib tashlar edi — bu real DB'da bo'lmaydi).
        * ICH-MA-ICH chaqiruv SAVEPOINT ochadi (yangi qulf/snapshot YO'Q):
          xatoda faqat ichki blok qaytadi, tashqi blok davom etadi.
        """
        parent = self._root
        if parent is not None:
            # SAVEPOINT — ich-ma-ich tranzaksiya.
            self.savepoints += 1
            snap = self._clone()
            cur = _FakeCursor(self)
            try:
                yield cur
            except BaseException:
                self._restore(snap)      # ROLLBACK TO SAVEPOINT
                raise
            if not commit:
                self._restore(snap)
            return

        # ILDIZ tranzaksiya: avval QULF, keyin snapshot (serializatsiya).
        self.lock.acquire()
        snap = self._clone()
        self._root = snap
        cur = _FakeCursor(self)
        try:
            yield cur
        except BaseException:
            self._restore(snap)          # ROLLBACK — yarim yozuv qolmaydi
            self._root = None
            self.lock.release()
            raise
        if not commit:
            self._restore(snap)          # o'qish rejimi: COMMIT yo'q
        self._root = None
        self.lock.release()

    # ---- SQL bajarish (real so'rov matnlari bo'yicha) -----------------
    def run(self, sql, params):
        s = " ".join(str(sql).split())
        p = tuple(params or ())

        # users qatorini QULFLASH (SELECT ... FOR UPDATE)
        if s.startswith("SELECT COALESCE(plan_type, 'free')") and "FOR UPDATE" in s:
            u = self.users.get(int(p[0]))
            if u is None:
                return []
            return [(u["plan"], u["used"], u["credits"])]

        # kunlik sanagichni yangilash (kun o'tgan bo'lsa)
        if s.startswith("UPDATE users SET ai_requests_today = 0, last_limit_reset"):
            uid = int(p[0])
            u = self.users.get(uid)
            if u and u["reset"] < datetime.now(timezone.utc).date():
                u["used"] = 0
                u["reset"] = datetime.now(timezone.utc).date()
            return []

        # obuna muddati (lazy downgrade uchun)
        if s.startswith("SELECT subscription_expires_at FROM users"):
            u = self.users.get(int(p[0]))
            return [(u["expires"],)] if u else []

        # muddati o'tgan PRO → FREE (lazy downgrade)
        if s.startswith("UPDATE users SET plan_type = 'free'"):
            u = self.users.get(int(p[0]))
            if u:
                u["plan"] = "free"
            return []

        # joriy kunlik sanagich
        if s.startswith("SELECT COALESCE(ai_requests_today, 0) FROM users"):
            u = self.users.get(int(p[0]))
            return [(u["used"],)] if u else []

        # KREDIT yechish (CreditsService._spend_in_tx — shartli atomik UPDATE)
        if s.startswith("UPDATE users SET ai_credits = ai_credits -"):
            amount, uid, required = int(p[0]), int(p[1]), int(p[2])
            u = self.users.get(uid)
            if u is None or u["credits"] < required:
                return []                # yechilmadi → InsufficientCreditsError
            u["credits"] -= amount
            return [(u["credits"],)]

        # KVOTA bron qilish (shartli atomik UPDATE)
        if s.startswith("UPDATE users SET ai_requests_today = COALESCE(ai_requests_today, 0) +"):
            cost, uid, cost2, limit = int(p[0]), int(p[1]), int(p[2]), int(p[3])
            u = self.users.get(uid)
            if u is None or u["used"] + cost2 > limit:
                return []                # bron qilinmadi → kredit zanjiriga o'tadi
            u["used"] += cost
            return [(u["used"],)]

        # Kredit yechilmaganda aniq sabab (CreditsService._spend_in_tx)
        if s.startswith("SELECT ai_credits FROM users"):
            u = self.users.get(int(p[0]))
            return [(u["credits"],)] if u else []

        # KREDITNI QAYTARISH (CreditsService._add_in_tx)
        if s.startswith("UPDATE users SET ai_credits = COALESCE(ai_credits, 0) +"):
            amount, uid = int(p[0]), int(p[1])
            u = self.users.get(uid)
            if u is None:
                return []
            u["credits"] += amount
            return [(u["credits"],)]

        # KVOTANI QAYTARISH (refund: GREATEST(... - cost, 0))
        if s.startswith("UPDATE users SET ai_requests_today = GREATEST("):
            cost, uid = int(p[0]), int(p[1])
            u = self.users.get(uid)
            if u:
                u["used"] = max(u["used"] - cost, 0)
            return []

        # bron qatorini yozish
        if s.startswith("INSERT INTO ai_reservations"):
            uid, op, cost, source, status = p
            self._res_seq += 1
            rid = self._res_seq
            self.reservations[rid] = {
                "id": rid, "user_id": int(uid), "operation_type": str(op),
                "cost": int(cost), "source": str(source), "status": str(status),
                "refunded_at": None,
            }
            return [(rid,)]

        # audit yozuvi (credits_ledger)
        if s.startswith("INSERT INTO credits_ledger"):
            uid, amount, balance_after, op, ref = p
            self._ledger_seq += 1
            lid = self._ledger_seq
            self.ledger.append({
                "id": lid, "user_id": int(uid), "amount": int(amount),
                "balance_after": int(balance_after), "operation_type": str(op),
                "reference_id": ref,
            })
            return [(lid,)]

        # bronni qaytarish (IDEMPOTENT: faqat 'active' bron qaytadi)
        if s.startswith("UPDATE ai_reservations SET status ="):
            status, rid, uid, active = p
            r = self.reservations.get(int(rid))
            if r is None or r["user_id"] != int(uid) or r["status"] != str(active):
                return []
            r["status"] = str(status)
            r["refunded_at"] = datetime.now(timezone.utc)
            return [(r["source"], r["cost"])]

        # refund sababini aniqlash
        if s.startswith("SELECT status, source FROM ai_reservations"):
            rid, uid = int(p[0]), int(p[1])
            r = self.reservations.get(rid)
            if r is None or r["user_id"] != uid:
                return []
            return [(r["status"], r["source"])]

        raise AssertionError(f"FakePG: kutilmagan SQL: {s[:160]}")


class _FakeCursor:
    def __init__(self, pg):
        self._pg = pg
        self._rows = []

    def execute(self, sql, params=None):
        self._rows = list(self._pg.run(sql, params))

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def close(self):
        pass


def install_fake(db, pg):
    """``database.db_transaction`` ni in-memory dvijok bilan almashtiradi."""
    original = db.db_transaction
    db.db_transaction = pg.tx
    return original


def restore_fake(db, original):
    db.db_transaction = original


# ---------------------------------------------------------------------------
# MODULLAR (env sozlangandan KEYIN import qilinadi)
# ---------------------------------------------------------------------------
import database as db                                      # noqa: E402
from services import ai_quota as aq                        # noqa: E402
from services import credits_service as cs                 # noqa: E402
from services.credits_service import CreditsService        # noqa: E402

FREE_DAILY_AI = db.PLAN_LIMITS["free"]["daily_ai_requests"]


def new_pg(**user_kwargs):
    pg = FakePG()
    return pg


# ============================================================
# TEST 1 — 5 PARALLEL SO'ROV, BALANSDA 1 KREDIT → 1 RUXSAT
# ============================================================
def test_parallel_credit_race():
    section("TEST 1: balansda 1 kredit, 5 parallel → AYNAN 1 ta ruxsat")
    pg = FakePG()
    pg.add_user(771001, plan="free", used=FREE_DAILY_AI, credits=1)
    orig = install_fake(db, pg)
    try:
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(
                lambda _: db.reserve_ai_request(771001, "magic_post", 1),
                range(5)))
    finally:
        restore_fake(db, orig)

    allowed = [r for r in results if r.get("allowed")]
    denied = [r for r in results if not r.get("allowed")]
    check("5 parallel → AYNAN 1 ta ruxsat (race condition yo'q)",
          len(allowed) == 1, f"allowed={len(allowed)}")
    check("qolgan 4 tasi RAD etildi", len(denied) == 4, f"denied={len(denied)}")
    check("rad sababi 'insufficient_balance'",
          all(r.get("reason") == "insufficient_balance" for r in denied),
          str([r.get("reason") for r in denied]))
    check("ruxsat etilgani kreditdan yechdi (source='credit')",
          allowed and allowed[0].get("source") == "credit",
          str(allowed and allowed[0]))
    check("balans 1 → 0 (manfiyga tushmadi)",
          pg.snapshot(771001)["credits"] == 0, str(pg.snapshot(771001)))
    check("aynan 1 ta bron qatori yozildi",
          len(pg.active_reservations(771001)) == 1,
          str(len(pg.active_reservations(771001))))
    check("credits_ledger'da AYNAN 1 ta -1 yozuv (audit atomik)",
          len(pg.ledger) == 1 and pg.ledger[0]["amount"] == -1, str(pg.ledger))
    check("ledger yozuvi bron ID'siga bog'langan",
          pg.ledger and pg.ledger[0]["reference_id"] ==
          f"ai_reservation:{allowed[0]['reservation_id']}",
          str(pg.ledger))


# ============================================================
# TEST 2 — 5 PARALLEL, KUNLIK KVOTA 3 → 3 RUXSAT
# ============================================================
def test_parallel_quota_race():
    section(f"TEST 2: kunlik kvota 3, 5 parallel → AYNAN 3 ta ruxsat "
            f"(limit {FREE_DAILY_AI})")
    pg = FakePG()
    pg.add_user(771002, plan="free", used=FREE_DAILY_AI - 3, credits=0)
    orig = install_fake(db, pg)
    try:
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(
                lambda _: db.reserve_ai_request(771002, "ai_studio", 1),
                range(5)))
    finally:
        restore_fake(db, orig)

    allowed = [r for r in results if r.get("allowed")]
    check("5 parallel → AYNAN 3 ta ruxsat (qator qulfi)",
          len(allowed) == 3, f"allowed={len(allowed)}")
    check("kunlik sanagich limitdan OSHMADI",
          pg.snapshot(771002)["used"] == FREE_DAILY_AI,
          str(pg.snapshot(771002)))
    check("barcha ruxsatlar bepul kvotadan (source='daily_quota')",
          all(r.get("source") == "daily_quota" for r in allowed),
          str([r.get("source") for r in allowed]))
    check("kredit yechilmadi (balans 0 qoldi)",
          pg.snapshot(771002)["credits"] == 0 and not pg.ledger,
          str(pg.ledger))
    check("rad etilgan 2 tasida reason='insufficient_balance'",
          [r for r in results if not r.get("allowed")] and all(
              r.get("reason") == "insufficient_balance"
              for r in results if not r.get("allowed")))


# ============================================================
# TEST 3 — DB XATOSI → QAT'IY FAIL-CLOSED
# ============================================================
def test_db_error_fail_closed():
    section("TEST 3: DB xatosi → FAIL-CLOSED (allowed=False, db_error)")
    pg = FakePG()
    pg.add_user(771003, plan="free", used=0, credits=50)

    @contextmanager
    def broken_tx(*args, **kwargs):
        raise RuntimeError("pool timeout (mock)")
        yield  # pragma: no cover

    orig = db.db_transaction
    db.db_transaction = broken_tx
    try:
        result = db.reserve_ai_request(771003, "magic_post", 1)
    finally:
        db.db_transaction = orig

    check("DB xatosida ruxsat YO'Q (fail-closed)",
          result.get("allowed") is False, str(result))
    check("sabab 'db_error'", result.get("reason") == "db_error", str(result))
    check("reservation_id yo'q (yarim bron qolmadi)",
          result.get("reservation_id") is None, str(result))
    check("used=-1 (infratuzilma xatosi signali)",
          result.get("used") == -1, str(result))

    # Xato tranzaksiya ichida (SQL bajarilgandan keyin) bo'lsa ham fail-closed.
    pg2 = FakePG()
    pg2.add_user(771004, plan="free", used=0, credits=50)

    class _Boom(FakePG):
        def run(self, sql, params):
            s = " ".join(str(sql).split())
            if s.startswith("INSERT INTO ai_reservations"):
                raise RuntimeError("disk to'ldi (mock)")
            return super().run(sql, params)

    pg2.__class__ = _Boom
    orig2 = install_fake(db, pg2)
    try:
        result2 = db.reserve_ai_request(771004, "magic_post", 1)
    finally:
        restore_fake(db, orig2)
    check("tranzaksiya ichidagi xato ham fail-closed",
          result2.get("allowed") is False
          and result2.get("reason") == "db_error", str(result2))
    check("ROLLBACK: balans o'zgarmadi (50 qoldi)",
          pg2.snapshot(771004)["credits"] == 50, str(pg2.snapshot(771004)))
    check("ROLLBACK: kunlik sanagich o'zgarmadi (0 qoldi)",
          pg2.snapshot(771004)["used"] == 0, str(pg2.snapshot(771004)))
    check("ROLLBACK: yarim bron qatori qolmadi",
          pg2.active_reservations(771004) == [], str(pg2.reservations))
    check("ROLLBACK: ledger'da yozuv yo'q", pg2.ledger == [], str(pg2.ledger))


# ============================================================
# TEST 4 — MABLAG' YETISHMASA YARIM YOZUV QOLMAYDI
# ============================================================
def test_insufficient_leaves_no_trace():
    section("TEST 4: kvota ham kredit ham yo'q → rad, bazada iz QOLMAYDI")
    pg = FakePG()
    pg.add_user(771005, plan="free", used=FREE_DAILY_AI, credits=0)
    orig = install_fake(db, pg)
    try:
        result = db.reserve_ai_request(771005, "voice_post", 1)
    finally:
        restore_fake(db, orig)

    check("rad etildi", result.get("allowed") is False, str(result))
    check("sabab 'insufficient_balance'",
          result.get("reason") == "insufficient_balance", str(result))
    check("mavjud balans qaytarildi (credits_left=0)",
          result.get("credits_left") == 0, str(result))
    check("YARIM BRON QATORI QOLMADI (SAVEPOINT rollback)",
          len(pg.reservations) == 0, str(pg.reservations))
    check("ledger'da yozuv yo'q", pg.ledger == [], str(pg.ledger))
    check("kunlik sanagich o'zgarmadi",
          pg.snapshot(771005)["used"] == FREE_DAILY_AI,
          str(pg.snapshot(771005)))
    check("balans manfiyga tushmadi",
          pg.snapshot(771005)["credits"] == 0, str(pg.snapshot(771005)))

    # Foydalanuvchi bazada umuman bo'lmasa ham fail-closed.
    pg2 = FakePG()
    orig2 = install_fake(db, pg2)
    try:
        result2 = db.reserve_ai_request(779999, "magic_post", 1)
    finally:
        restore_fake(db, orig2)
    check("mavjud bo'lmagan user → rad (user_not_found)",
          result2.get("allowed") is False
          and result2.get("reason") == "user_not_found", str(result2))


# ============================================================
# TEST 5 — KVOTA KREDITDAN AVVAL SARFLANADI
# ============================================================
def test_quota_before_credit():
    section("TEST 5: bepul kunlik kvota AVVAL, kredit keyin sarflanadi")
    pg = FakePG()
    pg.add_user(771006, plan="free", used=0, credits=10)
    orig = install_fake(db, pg)
    try:
        r1 = db.reserve_ai_request(771006, "magic_post", 1)
        r2 = db.reserve_ai_request(771006, "magic_post", 1)
    finally:
        restore_fake(db, orig)

    check("birinchi bron bepul kvotadan (source='daily_quota')",
          r1.get("allowed") and r1.get("source") == "daily_quota", str(r1))
    check("birinchi bronda kredit TEGILMADI (10 qoldi)",
          pg.snapshot(771006)["credits"] == 10, str(pg.snapshot(771006)))
    check("ledger'da yozuv yo'q (kvota audit talab qilmaydi)",
          pg.ledger == [], str(pg.ledger))
    check("ikkinci bron ham kvotadan", r2.get("source") == "daily_quota", str(r2))
    check("kunlik sanagich 2 ga oshdi",
          pg.snapshot(771006)["used"] == 2, str(pg.snapshot(771006)))

    # Kvota tugagach → kredit zanjiri.
    pg2 = FakePG()
    pg2.add_user(771007, plan="free", used=FREE_DAILY_AI, credits=2)
    orig2 = install_fake(db, pg2)
    try:
        r3 = db.reserve_ai_request(771007, "image_post", 1)
        r4 = db.reserve_ai_request(771007, "image_post", 1)
        r5 = db.reserve_ai_request(771007, "image_post", 1)
    finally:
        restore_fake(db, orig2)
    check("kvota tugach kreditdan yechildi (source='credit')",
          r3.get("allowed") and r3.get("source") == "credit", str(r3))
    check("ikkinchi so'rov ham kreditdan yechildi (source='credit')",
          r4.get("allowed") and r4.get("source") == "credit", str(r4))
    check("balans 2 → 1 → 0", pg2.snapshot(771007)["credits"] == 0,
          str(pg2.snapshot(771007)))
    check("uchinchi so'rov rad etildi (kredit tugadi)",
          r5.get("allowed") is False
          and r5.get("reason") == "insufficient_balance", str(r5))


# ============================================================
# TEST 6 — REFUND ATOMIK VA IDEMPOTENT
# ============================================================
def test_refund_is_atomic_and_idempotent():
    section("TEST 6: refund_ai_request — ATOMIK va IDEMPOTENT")
    # 6a) KREDIT manbasi: balans va ledger qaytadi, ikki marta EMAS.
    pg = FakePG()
    pg.add_user(771008, plan="free", used=FREE_DAILY_AI, credits=3)
    orig = install_fake(db, pg)
    try:
        res = db.reserve_ai_request(771008, "magic_post", 1)
        rid = res.get("reservation_id")
        check("bron qilindi (kredit 3 → 2)",
              res.get("allowed") and pg.snapshot(771008)["credits"] == 2,
              str((res, pg.snapshot(771008))))

        first = db.refund_ai_request(771008, rid)
        check("1-refund muvaffaqiyatli", first.get("success") is True, str(first))
        check("refund sababi 'refunded'", first.get("reason") == "refunded",
              str(first))
        check("kredit qaytdi (2 → 3)",
              pg.snapshot(771008)["credits"] == 3,
              str(pg.snapshot(771008)))
        check("ledger'da +1 'ai_refund' auditi bor",
              any(r["amount"] == 1 and r["operation_type"] == "ai_refund"
                  for r in pg.ledger), str(pg.ledger))
        check("bron holati 'refunded'",
              pg.reservations[rid]["status"] == "refunded",
              str(pg.reservations[rid]))

        second = db.refund_ai_request(771008, rid)
        check("2-refund RAD etildi (idempotent)",
              second.get("success") is False
              and second.get("reason") == "already_refunded", str(second))
        check("balans OSHIB KETMADI (3 qoldi)",
              pg.snapshot(771008)["credits"] == 3,
              str(pg.snapshot(771008)))

        third = db.refund_ai_request(771008, 999999)
        check("noma'lum bron → 'not_found'",
              third.get("success") is False and third.get("reason") == "not_found",
              str(third))

        # Parallel refund urinishlari — faqat bittasi o'tadi.
        pg.add_user(771020, plan="free", used=FREE_DAILY_AI, credits=5)
        res2 = db.reserve_ai_request(771020, "ai_studio", 1)
        check("parallel refund uchun bron qilindi (5 → 4)",
              res2.get("allowed") is True and res2.get("source") == "credit"
              and pg.users[771020]["credits"] == 4,
              str((res2, pg.users.get(771020))))
        rid2 = res2.get("reservation_id")
        with ThreadPoolExecutor(max_workers=5) as pool:
            refunds = list(pool.map(
                lambda _: db.refund_ai_request(771020, rid2), range(5)))
        ok_refunds = [r for r in refunds if r.get("success")]
        check("5 parallel refund → AYNAN 1 ta qaytaruv",
              len(ok_refunds) == 1, f"ok={len(ok_refunds)}")
        check("qolgan 4 tasi 'already_refunded' (idempotent)",
              sum(1 for r in refunds
                  if r.get("reason") == "already_refunded") == 4,
              str([r.get("reason") for r in refunds]))
        # Eslatma: balans TIRIK holatdan o'qiladi — ROLLBACK snapshot'ni
        # tiklaganidan keyin eski dict nusxasi eskirgan bo'ladi.
        check("balans 4 → 5 (AYNAN bir marta qaytdi, ikki marta emas)",
              pg.users[771020]["credits"] == 5,
              str(pg.users.get(771020)))

        # 6b) KUNLIK KVOTA manbasi: sanagich qaytadi, kredit tegilmaydi.
        restore_fake(db, orig)
        pg3 = FakePG()
        pg3.add_user(771010, plan="free", used=0, credits=7)
        orig = install_fake(db, pg3)
        res3 = db.reserve_ai_request(771010, "post_score", 1)
        check("kvota bron qilindi (used=1)",
              res3.get("source") == "daily_quota"
              and pg3.snapshot(771010)["used"] == 1, str(res3))
        ref3 = db.refund_ai_request(771010, res3.get("reservation_id"))
        check("kvota refund qilindi (used 1 → 0)",
              ref3.get("success") and pg3.snapshot(771010)["used"] == 0,
              str((ref3, pg3.snapshot(771010))))
        check("kvota refund'ida kredit TEGILMADI (7 qoldi)",
              pg3.snapshot(771010)["credits"] == 7,
              str(pg3.snapshot(771010)))
        check("kvota refund'ida ledger yozuvi yo'q",
              pg3.ledger == [], str(pg3.ledger))
        db.refund_ai_request(771010, res3.get("reservation_id"))
        check("kunlik sanagich manfiyga tushmadi (0 qoldi)",
              pg3.snapshot(771010)["used"] == 0,
              str(pg3.snapshot(771010)))
    finally:
        restore_fake(db, orig)

    # 6c) Refund DB xatosida fail-closed (yarim qaytaruv yo'q).
    @contextmanager
    def broken_tx(*args, **kwargs):
        raise RuntimeError("db uzildi (mock)")
        yield  # pragma: no cover

    orig_broken = db.db_transaction
    db.db_transaction = broken_tx
    try:
        ref_bad = db.refund_ai_request(771010, 1)
    finally:
        db.db_transaction = orig_broken
    check("refund DB xatosida fail-closed (success=False, db_error)",
          ref_bad.get("success") is False
          and ref_bad.get("reason") == "db_error", str(ref_bad))


# ============================================================
# TEST 7 — ARGUMENT VALIDATSIYASI FAIL-CLOSED
# ============================================================
def test_argument_validation_fail_closed():
    section("TEST 7: yaroqsiz argumentlar → rad (DB'ga tegmasdan)")
    cases = (
        ("cost=0", lambda: db.reserve_ai_request(771011, "magic_post", 0)),
        ("cost=-5", lambda: db.reserve_ai_request(771011, "magic_post", -5)),
        ("cost=10**6", lambda: db.reserve_ai_request(771011, "magic_post", 10 ** 6)),
        ("cost='abc'", lambda: db.reserve_ai_request(771011, "magic_post", "abc")),
        ("operation_type='drop_table'",
         lambda: db.reserve_ai_request(771011, "drop_table", 1)),
        ("operation_type=None",
         lambda: db.reserve_ai_request(771011, None, 1)),
        ("user_id='abc'", lambda: db.reserve_ai_request("abc", "magic_post", 1)),
        ("user_id=None", lambda: db.reserve_ai_request(None, "magic_post", 1)),
    )
    for label, call in cases:
        res = call()
        check(f"{label} → rad (invalid_request, fail-closed)",
              res.get("allowed") is False
              and res.get("reason") == "invalid_request"
              and res.get("reservation_id") is None, str(res))

    # Oq ro'yxatdagi barcha oqimlar qabul qilinadi (belgilash bilan ham).
    pg = FakePG()
    pg.add_user(771012, plan="free", used=0, credits=100)
    orig = install_fake(db, pg)
    try:
        for op in db.AI_OPERATION_TYPES:
            res = db.reserve_ai_request(771012, op, 1)
            check(f"oq ro'yxatdagi '{op}' qabul qilindi",
                  res.get("allowed") is True, str(res))
        res = db.reserve_ai_request(771012, "magic_post:sales", 1)
        check("belgilash ('magic_post:sales') qabul qilindi",
              res.get("allowed") is True, str(res))
        check("belgilash asos qismiga normallashtirildi",
              pg.reservations[res["reservation_id"]]["operation_type"]
              == "magic_post",
              str(pg.reservations[res["reservation_id"]]))
    finally:
        restore_fake(db, orig)

    # refund: yaroqsiz ID → rad (DB'ga tegmasdan).
    for bad in (None, 0, -1, "abc"):
        ref = db.refund_ai_request(771012, bad)
        check(f"refund id={bad!r} → invalid_reservation",
              ref.get("success") is False
              and ref.get("reason") == "invalid_reservation", str(ref))


# ============================================================
# TEST 8 — services/ai_quota ADAPTERI (atomik + legacy + fail-closed)
# ============================================================
def test_service_adapter():
    section("TEST 8: services/ai_quota — atomik yo'l, legacy va fail-closed")

    def run(coro):
        return asyncio.run(coro)

    # 8a) Haqiqiy DB adapteri (run_db.__module__ == "database") → ATOMIK yo'l.
    calls = []

    def fake_reserve(user_id, op, cost):
        calls.append(("reserve_ai_request", user_id, op, cost))
        return {"allowed": True, "reason": "ok", "reservation_id": 4242,
                "source": "credit", "cost": 1, "used": 3, "max_ai": 10,
                "credits_left": 7}

    real_adapter = SimpleNamespace(
        run_db=db.run_db, reserve_ai_request=fake_reserve)
    check("haqiqiy adapter aniqlandi (run_db.__module__ == 'database')",
          aq._is_real_db_adapter(real_adapter) is True)
    out = run(aq.reserve_ai_quota(real_adapter, 771013, "magic_post", 1))
    check("atomik funksiya chaqirildi",
          calls == [("reserve_ai_request", 771013, "magic_post", 1)], str(calls))
    check("natija atomik bron (reservation_id=4242, legacy=False)",
          out.get("allowed") is True and out.get("reservation_id") == 4242
          and out.get("legacy") is False, str(out))

    # 8b) Atomik funksiya istisno tashlasa ham FAIL-CLOSED.
    def boom_reserve(*a, **k):
        raise RuntimeError("db uzildi (mock)")

    boom_adapter = SimpleNamespace(run_db=db.run_db,
                                   reserve_ai_request=boom_reserve)
    out2 = run(aq.reserve_ai_quota(boom_adapter, 771014, "magic_post", 1))
    check("atomik funksiya xatosida FAIL-CLOSED (allowed=False, db_error)",
          out2.get("allowed") is False and out2.get("reason") == "db_error",
          str(out2))

    # 8c) Eski test adapteri (run_db almashtirilgan) → LEGACY zanjir.
    legacy_calls = []

    async def fake_run_db(func, *args, **kwargs):
        name = getattr(func, "__name__", str(func))
        legacy_calls.append(name)
        if name == "check_ai_limit":
            return (True, 1, 30)
        if name == "use_user_credit":
            return True
        if name == "add_user_credit":
            return True
        if name == "refund_ai_usage":
            return True
        return None

    legacy_adapter = SimpleNamespace(
        run_db=fake_run_db,
        check_ai_limit=db.check_ai_limit,
        use_user_credit=db.use_user_credit,
        add_user_credit=db.add_user_credit,
        refund_ai_usage=db.refund_ai_usage,
    )
    check("test adapteri legacy deb tanildi",
          aq._is_real_db_adapter(legacy_adapter) is False)
    out3 = run(aq.reserve_ai_quota(legacy_adapter, 771015, "magic_post", 1))
    check("legacy zanjir: check_ai_limit + use_user_credit AYNAN 1 martadan",
          legacy_calls.count("check_ai_limit") == 1
          and legacy_calls.count("use_user_credit") == 1, str(legacy_calls))
    check("legacy bron muvaffaqiyatli (legacy=True, reservation_id=None)",
          out3.get("allowed") is True and out3.get("legacy") is True
          and out3.get("reservation_id") is None, str(out3))

    legacy_calls.clear()
    ok = run(aq.release_ai_quota(legacy_adapter, 771015, None))
    check("legacy refund: add_user_credit + refund_ai_usage chaqirildi",
          ok is True and "add_user_credit" in legacy_calls
          and "refund_ai_usage" in legacy_calls, str(legacy_calls))

    # 8d) Legacy zanjirda kredit yetishmasa → bron qilingan kvota QAYTADI.
    legacy_calls2 = []

    async def fake_run_db2(func, *args, **kwargs):
        name = getattr(func, "__name__", str(func))
        legacy_calls2.append(name)
        if name == "check_ai_limit":
            return (True, 2, 30)
        if name == "use_user_credit":
            return False                 # kredit tugagan
        if name in ("add_user_credit", "refund_ai_usage"):
            return True
        return None

    legacy2 = SimpleNamespace(
        run_db=fake_run_db2,
        check_ai_limit=db.check_ai_limit,
        use_user_credit=db.use_user_credit,
        add_user_credit=db.add_user_credit,
        refund_ai_usage=db.refund_ai_usage,
    )
    out4 = run(aq.reserve_ai_quota(legacy2, 771016, "magic_post", 1))
    check("kredit yetishmasa legacy bron RAD etildi",
          out4.get("allowed") is False
          and out4.get("reason") == "insufficient_balance", str(out4))
    check("bron qilingan kunlik kvota qaytarildi (refund_ai_usage)",
          "refund_ai_usage" in legacy_calls2, str(legacy_calls2))

    # 8e) Legacy zanjirda DB xatosi → FAIL-CLOSED (eski fail-open yo'q).
    async def broken_run_db(func, *args, **kwargs):
        raise RuntimeError("pool band (mock)")

    broken = SimpleNamespace(
        run_db=broken_run_db,
        check_ai_limit=db.check_ai_limit,
        use_user_credit=db.use_user_credit,
        add_user_credit=db.add_user_credit,
        refund_ai_usage=db.refund_ai_usage,
    )
    out5 = run(aq.reserve_ai_quota(broken, 771017, "magic_post", 1))
    check("legacy zanjirda DB xatosi → FAIL-CLOSED (db_error)",
          out5.get("allowed") is False and out5.get("reason") == "db_error",
          str(out5))

    # 8f) Adapter umuman javob bermasa (None) ham ruxsat berilmaydi.
    async def silent_run_db(func, *args, **kwargs):
        return None

    silent = SimpleNamespace(
        run_db=silent_run_db,
        check_ai_limit=db.check_ai_limit,
        use_user_credit=db.use_user_credit,
        add_user_credit=db.add_user_credit,
        refund_ai_usage=db.refund_ai_usage,
    )
    out6 = run(aq.reserve_ai_quota(silent, 771018, "magic_post", 1))
    check("adapter javob bermasa → rad (fail-closed)",
          out6.get("allowed") is False, str(out6))

    # 8g) Atomik refund adapter orqali (haqiqiy db) → refund_ai_request.
    refund_calls = []

    def fake_refund(user_id, rid):
        refund_calls.append(("refund_ai_request", user_id, rid))
        return {"success": True, "reason": "refunded",
                "reservation_id": rid, "source": "credit"}

    refund_adapter = SimpleNamespace(run_db=db.run_db,
                                     refund_ai_request=fake_refund)
    ok2 = run(aq.release_ai_quota(refund_adapter, 771019, 55))
    check("atomik refund chaqirildi (reservation_id=55)",
          ok2 is True and refund_calls == [("refund_ai_request", 771019, 55)],
          str(refund_calls))

    # 8h) Sabab tasnifi (handler matn tanlashi uchun).
    check("insufficient_balance → mablag' sababi",
          aq.is_balance_reason("insufficient_balance") is True)
    check("db_error → vaqtinchalik xato sababi",
          aq.is_temp_error_reason("db_error") is True
          and aq.is_balance_reason("db_error") is False)
    check("kvota tugagani aniqlanadi (used >= max_ai)",
          aq.is_quota_exhausted({"reason": "insufficient_balance",
                                 "used": 10, "max_ai": 10}) is True)
    check("kredit tugagani kvota deb hisoblanmaydi (used < max_ai)",
          aq.is_quota_exhausted({"reason": "insufficient_balance",
                                 "used": 2, "max_ai": 10}) is False)
    check("vaqtinchalik xato matni 3 tilda ham bor (hardcode yo'q)",
          all(aq.ai_quota_temp_error_text(l) for l in ("uz", "ru", "en"))
          and len({aq.ai_quota_temp_error_text(l) for l in ("uz", "ru", "en")}) == 3)

    # 8i) HAQIQIY adapter + HAQIQIY tranzaksiya kodi + handler konteksti:
    # reserve_for_flow bron ID'sini kontekstga yozadi, take_reservation_id
    # uni OLADI (pop) — shunda ikkinchi refund imkonsiz bo'ladi.
    pg4 = FakePG()
    pg4.add_user(771021, plan="free", used=0, credits=4)
    orig4 = install_fake(db, pg4)
    try:
        ctx = SimpleNamespace(user_data={"magic_style": "sales"})
        res4 = run(aq.reserve_for_flow(db, ctx, 771021, "magic_post", "magic", 1))
        check("handler oqimi: atomik bron muvaffaqiyatli (haqiqiy kod yo'li)",
              res4.get("allowed") is True and res4.get("legacy") is False,
              str(res4))
        check("bron ID'si kontekstga yozildi (magic_reservation_id)",
              ctx.user_data.get("magic_reservation_id")
              == res4.get("reservation_id"), str(ctx.user_data))
        check("bron manbasi kontekstga yozildi (magic_reservation_source)",
              ctx.user_data.get("magic_reservation_source") == "daily_quota",
              str(ctx.user_data))
        taken = aq.take_reservation_id(ctx, "magic")
        check("take_reservation_id ID'ni OLADI (pop)",
              taken == res4.get("reservation_id")
              and "magic_reservation_id" not in ctx.user_data
              and "magic_reservation_source" not in ctx.user_data,
              str(ctx.user_data))
        ok4 = run(aq.release_ai_quota(db, 771021, taken))
        check("oqim refund'i atomik bajarildi (kvota qaytdi)",
              ok4 is True and pg4.users[771021]["used"] == 0,
              str((ok4, pg4.users[771021])))
        # Eski (stale) bron ma'lumoti yangi oqimda avval tozalanadi.
        ctx2 = SimpleNamespace(user_data={"magic_reservation_id": 999,
                                          "magic_reservation_source": "credit"})
        res5 = run(aq.reserve_for_flow(db, ctx2, 771021, "magic_post",
                                       "magic", 1))
        check("stale bron ID'si yangi bron bilan ALMASHTIRILDI",
              res5.get("allowed") is True
              and ctx2.user_data.get("magic_reservation_id")
              == res5.get("reservation_id")
              and ctx2.user_data.get("magic_reservation_id") != 999,
              str(ctx2.user_data))
        # Boshqa oqim prefiksi bu bronni o'chirmaydi (parallel oqimlar).
        ctx3 = SimpleNamespace(user_data={})
        run(aq.reserve_for_flow(db, ctx3, 771021, "voice_post", "voice", 1))
        check("boshqa oqim prefiksi ('voice') 'magic' bronini buzmaydi",
              ctx2.user_data.get("magic_reservation_id")
              == res5.get("reservation_id"), str(ctx2.user_data))
    finally:
        restore_fake(db, orig4)


# ============================================================
# TEST 9 — BARChA AI OQIMLARI SHU FUNKSIYADAN FOYDALANADI
# ============================================================
def test_all_ai_flows_use_atomic_reserve():
    section("TEST 9: Magic Post / AI Studio / Voice / Image / Post Score "
            "→ yagona transactional funksiya")
    handlers_dir = ROOT / "handlers"
    flows = {
        "magic_post.py": ("magic_post", '"magic"'),
        "ai_assistant.py": ("ai_studio", '"studio"'),
        "voice_post.py": ("voice_post", '"voice"'),
        "image_post.py": ("image_post", None),
        "post_score.py": ("post_score", '"score"'),
    }
    for fname, (op, prefix) in flows.items():
        src = (handlers_dir / fname).read_text(encoding="utf-8")
        check(f"{fname}: services.ai_quota import qilingan",
              "from services.ai_quota import" in src)
        check(f"{fname}: '{op}' oqimi atomik bronga ulangan", op in src)
        # Fail-open qolmaganmi: "except ... → ruxsat berish" naqshlari.
        check(f"{fname}: fail-open naqshi YO'Q (can_use = True)",
              not re.search(r"can_use,\s*used,\s*max_ai\s*=\s*True", src))
        check(f"{fname}: fail-open naqshi YO'Q (reserved = True)",
              not re.search(r"reserved\s*=\s*True", src))
        check(f"{fname}: bevosita use_user_credit chaqiruvi YO'Q",
              "db.run_db(db.use_user_credit" not in src)
        if prefix:
            check(f"{fname}: bron {prefix} prefiksi bilan saqlanadi",
                  prefix in src)

    # Image oqimi o'z helperi orqali atomik funksiyani chaqiradi.
    img_src = (handlers_dir / "image_post.py").read_text(encoding="utf-8")
    check("image_post.py: reserve_ai_quota chaqiriladi",
          "reserve_ai_quota(db, user_id, \"image_post\", 1)" in img_src)
    check("image_post.py: refund_ai_request zanjiri (release_ai_quota) bor",
          "release_ai_quota(db, user_id, reservation_id)" in img_src)

    # Yagona manba: hech bir handler eski ikki qadamli zanjirni chaqirmaydi.
    for fname in flows:
        src = (handlers_dir / fname).read_text(encoding="utf-8")
        check(f"{fname}: eski check_ai_limit chaqiruvi YO'Q",
              "db.run_db(db.check_ai_limit" not in src)

    # Legacy zanjir backward compatibility uchun SAQLANGAN (eski test
    # adapterlari va eski deploy'lar uchun) — services/ai_quota.py ichida.
    quota_src = (ROOT / "services" / "ai_quota.py").read_text(encoding="utf-8")
    check("legacy alias saqlangan: check_ai_limit zanjiri mavjud",
          "db_module.check_ai_limit" in quota_src)
    check("legacy alias saqlangan: use_user_credit zanjiri mavjud",
          "db_module.use_user_credit" in quota_src)
    check("legacy refund aliaslari saqlangan (add_user_credit/refund_ai_usage)",
          "add_user_credit" in quota_src and "refund_ai_usage" in quota_src)

    # Eski DB funksiyalari O'CHIRILMAGAN (backward compatibility).
    for legacy in ("check_ai_limit", "use_user_credit", "refund_ai_usage",
                   "increment_ai_usage", "add_user_credit", "get_user_credits"):
        check(f"database.{legacy} hali ham mavjud (eski oqimlar buzilmadi)",
              callable(getattr(db, legacy, None)))

    # Schema: bron jadvali va FK startup tekshiruvida.
    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    check("schema.sql: ai_reservations jadvali bor (idempotent)",
          "CREATE TABLE IF NOT EXISTS ai_reservations (" in schema)
    check("schema.sql: source/status CHECK constraintlari bor",
          "chk_ai_reservations_source" in schema
          and "chk_ai_reservations_status" in schema)
    check("database.EXPECTED_TABLES: ai_reservations startup'da tekshiriladi",
          "ai_reservations" in db.EXPECTED_TABLES)
    check("FK constraint ro'yxatda (yetim bron qolmaydi)",
          any(c["name"] == "fk_ai_reservations_user"
              for c in db.INTEGRITY_CONSTRAINTS))
    check("credits_ledger'da 'ai_refund' turi ruxsat etilgan",
          CreditsService.OP_AI_REFUND == "ai_refund"
          and CreditsService.OP_AI_REFUND in cs.VALID_OPERATION_TYPES)

    # Atomiklik dalillari (kod darajasida).
    import inspect
    reserve_src = inspect.getsource(db.reserve_ai_request)
    check("reserve: qator QULFLANADI (SELECT ... FOR UPDATE)",
          "FOR UPDATE" in reserve_src)
    check("reserve: BITTA tranzaksiya bloki (db_cursor(commit=True))",
          reserve_src.count("db_cursor(commit=True)") == 1)
    check("reserve: kvota → kredit zanjiri bitta blokda",
          "AI_RESERVE_SOURCE_QUOTA" in reserve_src
          and "spend_in_tx" in reserve_src)
    check("reserve: har qanday xatoda FAIL-CLOSED (db_error)",
          "AI_RESERVE_DB_ERROR" in reserve_src)
    refund_src = inspect.getsource(db.refund_ai_request)
    check("refund: IDEMPOTENT (status = 'active' sharti bilan)",
          "AI_RESERVATION_ACTIVE" in refund_src
          and "UPDATE ai_reservations SET status" in refund_src)
    check("refund: manbaga qarab qaytaradi (kvota YOKI kredit)",
          "AI_RESERVE_SOURCE_QUOTA" in refund_src and "add_in_tx" in refund_src)


# ============================================================
def main():
    print("=" * 64)
    print(" 🔒 PHASE 2 / 1-QADAM — ATOMIK KVOTA + KREDIT TRANZAKSIYASI")
    print("=" * 64)

    test_parallel_credit_race()
    test_parallel_quota_race()
    test_db_error_fail_closed()
    test_insufficient_leaves_no_trace()
    test_quota_before_credit()
    test_refund_is_atomic_and_idempotent()
    test_argument_validation_fail_closed()
    test_service_adapter()
    test_all_ai_flows_use_atomic_reserve()

    print("\n" + "=" * 64)
    print(f" JAMI: PASS={passed}, FAIL={failures}")
    print("=" * 64)
    if failures:
        print("❌ ATOMIK KVOTA TESTLARIDA XATOLIKLAR BOR ^^^")
        sys.exit(1)
    print("✅ ATOMIK KVOTA + KREDIT TRANZAKSIYASI — 100% YASHIL ✔")


if __name__ == "__main__":
    main()
