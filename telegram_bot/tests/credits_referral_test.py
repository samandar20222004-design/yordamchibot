#!/usr/bin/env python3
"""PostAssist V2 — 8-BOSQICH: Credits Ledger auditi va Referal Anti-Abuse testi.

Nima tekshiriladi
----------------
1. **Static/lojika qismi (baza shart emas, doim ishlaydi)**:
   schema.sql'dagi ``credits_ledger`` DDL, database.py paralligi,
   CreditsService API (add/spend/history, InsufficientCreditsError,
   operation_type oq ro'yxati), parse_referral_code, self-referral
   tekshiruvi (DB'siz), va AI Studio / streak / save_user / transfer
   oqimlarining CreditsService'ga ulanishi (manba darajasida).

2. **Real PostgreSQL qismi** (pgserver yoki INTEGRITY_TEST_DATABASE_URL /
   P0_TEST_DATABASE_URL):
   - Self-referral rad etilishi (o'z havolasidan kirgan foydalanuvchiga
     bonus YO'Q, referrer biriktirilmaydi, ledger'ga yozuv tushmaydi);
   - Bir xil foydalanuvchi ikkita referral orqali o'tishga uringanda
     faqat BIRINCHISI hisoblanishi (takroriy kirishda bonus YO'Q,
     referrer o'zgarmaydi);
   - Ball yechilganda va qo'shilganda ``credits_ledger`` ga to'liq
     audit yozilishi (amount, balance_after zanjiri, operation_type,
     reference_id, tarix chegaralari);
   - Balans yetarli bo'lmaganda ball yechish bloklanishi
     (InsufficientCreditsError, hech qanday yozuv qolmaydi);
   - Qo'shimcha: parallel yechishda double-spend bo'lmasligi va
     tranzaksiya yiqilganda balans+ledger birga ROLLBACK bo'lishi.

Ishga tushirish
---------------
::

    cd telegram_bot && python tests/credits_referral_test.py

Real PG bo'lmasa (pgserver yo'q va URL berilmagan) — faqat static qism
bajariladi, live qismi SKIP (repo'dagi P0/integrity testlar kabi).
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

# Live test uchun alohida ID diapazoni (boshqa testlarga tegmaydi).
SELF_A = 80000001
SELF_B = 80000002
REF_MAIN = 80000010
REF_OTHER = 80000011
NEW_USER = 80000012
EXISTING = 80000013
AUDIT_USER = 80000020
POOR_USER = 80000030
ZERO_USER = 80000031
RACE_USER = 80000040
ATOMIC_USER = 80000050
ALL_IDS = (SELF_A, SELF_B, REF_MAIN, REF_OTHER, NEW_USER, EXISTING,
           AUDIT_USER, POOR_USER, ZERO_USER, RACE_USER, ATOMIC_USER)


# ============================================================
# 1. STATIC / LOJIKA (baza shart emas)
# ============================================================

def test_static_schema():
    print("== 8-bosqich: schema.sql va database.py paralligi ==")
    check("jadval: credits_ledger",
          "CREATE TABLE IF NOT EXISTS credits_ledger (" in SCHEMA)
    check("indeks: idx_ledger_user (user_id, created_at)",
          "CREATE INDEX IF NOT EXISTS idx_ledger_user "
          "ON credits_ledger(user_id, created_at);" in SCHEMA)
    for col in ("id BIGSERIAL PRIMARY KEY",
                "user_id BIGINT NOT NULL",
                "amount INT NOT NULL",
                "balance_after INT NOT NULL",
                "operation_type VARCHAR(32) NOT NULL",
                "reference_id TEXT",
                "created_at TIMESTAMPTZ DEFAULT NOW()"):
        check(f"ustun: {col}", col in SCHEMA)
    check("FK: fk_credits_ledger_user (DO bloki)",
          "fk_credits_ledger_user" in SCHEMA
          and "FOREIGN KEY (user_id) REFERENCES users(user_id)" in SCHEMA)

    import database as db_mod
    check("EXPECTED_TABLES: credits_ledger", "credits_ledger" in db_mod.EXPECTED_TABLES)
    check("EXPECTED_INDEXES: idx_ledger_user", "idx_ledger_user" in db_mod.EXPECTED_INDEXES)
    names = [item["name"] for item in db_mod.INTEGRITY_CONSTRAINTS]
    check("INTEGRITY_CONSTRAINTS: fk_credits_ledger_user", "fk_credits_ledger_user" in names)
    check("build_integrity_block() yangi FK'ni ham o'z ichiga oladi",
          "fk_credits_ledger_user" in db_mod.build_integrity_block())


def test_static_credits_service():
    print("== 8-bosqich: CreditsService API ==")
    from services.credits_service import (
        CreditsService, InsufficientCreditsError,
        OP_DAILY_BONUS, OP_REFERRAL, OP_AI_REQUEST, OP_PROMO, OP_ADMIN,
        VALID_OPERATION_TYPES, HISTORY_LIMIT_MAX,
    )

    for name in ("add_credits", "spend_credits", "get_user_history",
                 "add_in_tx", "spend_in_tx", "grant_in_tx"):
        check(f"CreditsService.{name} mavjud",
              callable(getattr(CreditsService, name, None)))
    check("InsufficientCreditsError istisnosi",
          issubclass(InsufficientCreditsError, Exception))
    required = {"daily_bonus", "referral", "ai_request", "promo", "admin"}
    check("operation_type oq ro'yxati topshiriqdagi 5 tani o'z ichiga oladi",
          required <= set(VALID_OPERATION_TYPES), str(VALID_OPERATION_TYPES))
    check("operation_type doimiylari to'g'ri",
          (OP_DAILY_BONUS, OP_REFERRAL, OP_AI_REQUEST, OP_PROMO, OP_ADMIN)
          == ("daily_bonus", "referral", "ai_request", "promo", "admin"))

    # Noto'g'ri kirishlar — DB'siz, validation'da ushlanadi.
    for bad_call, label in (
        (lambda: CreditsService.add_credits(1, 1, "noma'lum_op"),
         "add_credits(noma'lum op_type) → ValueError"),
        (lambda: CreditsService.spend_credits(1, 1, "noma'lum_op"),
         "spend_credits(noma'lum op_type) → ValueError"),
        (lambda: CreditsService.add_credits(1, -5, "promo"),
         "add_credits(manfiy) → ValueError"),
        (lambda: CreditsService.spend_credits(1, 0, "ai_request"),
         "spend_credits(0) → ValueError"),
    ):
        try:
            bad_call()
            check(label, False)
        except ValueError:
            check(label, True)
        except Exception as e:  # noqa: BLE001
            check(label, False, f"kutilmagan {type(e).__name__}")

    # get_user_history: foydalanuvchi ID noto'g'ri bo'lsa [] (DB'ga tegmaydi).
    check("get_user_history(not a number) → []",
          CreditsService.get_user_history("abc") == [])
    check("get_user_history limit cheklovi 100",
          HISTORY_LIMIT_MAX == 100)


def test_static_referral_service():
    print("== 8-bosqich: ReferralService (anti-abuse, DB'siz qism) ==")
    from services.referral_service import (
        ReferralService, parse_referral_code,
        REASON_SELF_REFERRAL, REASON_OK,
        REASON_EXISTING_USER, REASON_ALREADY_REREFERRED,
        REASON_UNKNOWN_REFERRER, REASON_NO_REFERRAL,
    )

    check("parse: ref_123 → 123", parse_referral_code("ref_123") == 123)
    check("parse: ref_007 → 7", parse_referral_code("ref_007") == 7)
    check("parse: ref_0 → None", parse_referral_code("ref_0") is None)
    check("parse: ref_abc → None", parse_referral_code("ref_abc") is None)
    check("parse: oddiy son → None", parse_referral_code("123") is None)
    check("parse: None → None", parse_referral_code(None) is None)
    check("parse: bo'sh satr → None", parse_referral_code("  ") is None)

    class _NoDb:
        def execute(self, *a, **k):
            raise AssertionError("self-referral tekshiruvi DB so'rovi talab qilmaydi")

    # Self-referral — darhol, hech qanday DB so'rovisiz rad etilishi kerak.
    ref, reason = ReferralService.validate_referral(_NoDb(), 42, 42)
    check("self-referral: referrer biriktirilmaydi", ref is None)
    check("self-referral: sabab 'self_referral'", reason == REASON_SELF_REFERRAL)
    ref2, reason2 = ReferralService.validate_referral(_NoDb(), 42, None)
    check("kod berilmagan: sabab 'no_referral'",
          ref2 is None and reason2 == REASON_NO_REFERRAL)

    sabablar = {REASON_OK, REASON_NO_REFERRAL, REASON_SELF_REFERRAL,
                REASON_EXISTING_USER, REASON_ALREADY_REREFERRED,
                REASON_UNKNOWN_REFERRER}
    check("barcha anti-abuse sabab doimiylari e'lon qilingan", len(sabablar) == 6)


def test_static_integration_wiring():
    print("== 8-bosqich: AI Studio / streak / transfer ulanishi ==")
    import inspect
    import database as db_mod

    src_use = inspect.getsource(db_mod.use_user_credit)
    check("AI Studio: use_user_credit → CreditsService.spend_credits",
          "spend_credits(" in src_use and "CreditsService" in src_use)
    check("AI Studio: op_type = ai_request", "OP_AI_REQUEST" in src_use)
    check("AI Studio: InsufficientCreditsError ushlanadi",
          "InsufficientCreditsError" in src_use)

    src_add = inspect.getsource(db_mod.add_user_credit)
    check("AI refund: add_user_credit → CreditsService.add_credits",
          "add_credits(" in src_add and "CreditsService" in src_add)

    src_streak = inspect.getsource(db_mod.claim_daily_streak_bonus)
    check("streak: bonus grant_in_tx orqali (shu tranzaksiyada)",
          "grant_in_tx(" in src_streak)
    check("streak: op_type = daily_bonus", "OP_DAILY_BONUS" in src_streak)

    src_save = inspect.getsource(db_mod.save_user)
    check("save_user → ReferralService.register_new_user (anti-abuse)",
          "register_new_user(" in src_save and "ReferralService" in src_save)

    src_tr = inspect.getsource(db_mod.transfer_user_credits)
    check("transfer: ikkala tomon op_type = transfer",
          "OP_TRANSFER" in src_tr and src_tr.count("in_tx(") >= 2)


# ============================================================
# 2. REAL POSTGRESQL (pgserver yoki URL)
# ============================================================

_local_server = []


def _live_uri():
    """Real PG URI: INTEGRITY_TEST_DATABASE_URL | P0_TEST_DATABASE_URL |
    DATABASE_URL | pgserver (vaqtinchalik lokal server)."""
    for var in ("INTEGRITY_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL"):
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
    import tempfile
    try:
        server = pgserver.get_server(
            os.path.join(tempfile.gettempdir(), "yordamchi_pg_credits"))
    except Exception:  # pragma: no cover - muhitga bog'liq
        return None
    _local_server.append(server)
    return server.get_uri()


def _balance(db_mod, uid):
    with db_mod.db_cursor() as cur:
        cur.execute("SELECT ai_credits FROM users WHERE user_id = %s", (uid,))
        row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _ref(db_mod, uid):
    with db_mod.db_cursor() as cur:
        cur.execute("SELECT referrer_id FROM users WHERE user_id = %s", (uid,))
        row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _ledger(db_mod, uid):
    """Ledger qatorlari (id o'sish tartibida) — audit zanjirini tekshirish uchun."""
    with db_mod.db_cursor() as cur:
        cur.execute(
            "SELECT id, amount, balance_after, operation_type, reference_id "
            "FROM credits_ledger WHERE user_id = %s ORDER BY id ASC", (uid,))
        return [
            {"id": int(r[0]), "amount": int(r[1]), "balance_after": int(r[2]),
             "operation_type": r[3], "reference_id": r[4]}
            for r in cur.fetchall()
        ]


def _chain_ok(db_mod, uid, start_balance):
    """balance_after zanjiri: har bir qatorda keyingi balans to'g'rimi?"""
    rows = _ledger(db_mod, uid)
    expected = int(start_balance)
    for row in rows:
        expected += row["amount"]
        if row["balance_after"] != expected:
            return False
    return True


def _ensure_user(db_mod, uid, credits=5, referrer=None):
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO users (user_id, username, ai_credits, referrer_id) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (user_id) DO UPDATE SET ai_credits = EXCLUDED.ai_credits, "
            "referrer_id = EXCLUDED.referrer_id",
            (uid, f"cr_{uid}", credits, referrer),
        )


def _cleanup(db_mod):
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM credits_ledger WHERE user_id = ANY(%s)",
                    (list(ALL_IDS),))
        cur.execute("DELETE FROM users WHERE user_id = ANY(%s)", (list(ALL_IDS),))


def test_live(self_db):
    db_mod = self_db
    from services.credits_service import CreditsService, InsufficientCreditsError
    from services.referral_service import ReferralService
    import psycopg2

    print("== 8-bosqich (live): schema real bazada ==")
    with db_mod.db_cursor() as cur:
        cur.execute("SELECT to_regclass('credits_ledger')")
        check("credits_ledger jadvali mavjud", cur.fetchone()[0] is not None)
        cur.execute("SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = current_schema() AND indexname = 'idx_ledger_user'")
        check("idx_ledger_user indeksi mavjud", cur.fetchone() is not None)
        cur.execute(
            "SELECT conname FROM pg_constraint c "
            "JOIN pg_class r ON r.oid = c.conrelid "
            "JOIN pg_namespace n ON n.oid = r.relnamespace "
            "WHERE n.nspname = current_schema() AND c.conname = 'fk_credits_ledger_user'")
        check("fk_credits_ledger_user constrainti mavjud", cur.fetchone() is not None)

    # FK himoyasi: yetim (mavjud foydalanuvchisiz) ledger yozuvi rad etiladi.
    try:
        with db_mod.db_transaction() as cur:
            cur.execute(
                "INSERT INTO credits_ledger (user_id, amount, balance_after, "
                "operation_type) VALUES (999999999, 1, 1, 'promo')")
        check("FK: yetim ledger yozuvi rad etildi", False)
    except psycopg2.Error:
        check("FK: yetim ledger yozuvi rad etildi", True)

    # ------------------------------------------------------------
    print("== 8-bosqich (live): 1) SELF-REFERRAL rad etiladi ==")
    # save_user orqali (haqiqiy /start oqimi)
    new = db_mod.save_user(SELF_A, "self_a", "Self A", referrer_id=SELF_A)
    check("self-referral: foydalanuvchi yaratiladi", new is True)
    check("self-referral: referrer biriktirilmadi", _ref(db_mod, SELF_A) is None)
    check("self-referral: bonus berilmadi (balans 5)", _balance(db_mod, SELF_A) == 5)
    check("self-referral: ledger yozuvi yo'q", _ledger(db_mod, SELF_A) == [])

    # Servis orqali (sabab kodi aniq)
    res = ReferralService.register_new_user(
        SELF_B, "self_b", referrer_id=SELF_B)
    check("self-referral: is_new=True", res["is_new"] is True)
    check("self-referral: sabab 'self_referral'",
          res["reason"] == "self_referral", str(res))
    check("self-referral: reward=0", res["reward"] == 0)

    # ------------------------------------------------------------
    print("== 8-bosqich (live): 2) TAKRORIY REFERRAL — faqat birinchisi ==")
    # Referrerlar avval botda bo'ladi (o'z havolasiz).
    db_mod.save_user(REF_MAIN, "ref_main")
    db_mod.save_user(REF_OTHER, "ref_other")

    # 1-urinish: yangi foydalanuvchi REF_MAIN havolasi bilan — BONUS BERE
    res1 = ReferralService.register_new_user(
        NEW_USER, "newbie", referrer_id=REF_MAIN)
    check("1-taklif: qabul qilindi (reason='ok')",
          res1["is_new"] is True and res1["reason"] == "ok", str(res1))
    check("1-taklif: reward=3 (birinchi do'st)", res1["reward"] == 3, str(res1))
    check("1-taklif: referrer saqlandi", _ref(db_mod, NEW_USER) == REF_MAIN)
    check("1-taklif: referrer balansi 5+3=8", _balance(db_mod, REF_MAIN) == 8)
    rows = _ledger(db_mod, REF_MAIN)
    check("1-taklif: ledger'ga +3 referral yozuvi",
          len(rows) == 1 and rows[0]["amount"] == 3
          and rows[0]["balance_after"] == 8
          and rows[0]["operation_type"] == "referral"
          and rows[0]["reference_id"] == str(NEW_USER),
          str(rows))

    # 2-urinish: xuddi shu foydalanuvchi BOSHQA referrer havolasi bilan
    # qayta kirdi (masalan, botni qayta /start qildi) — bonus YO'Q.
    res2 = ReferralService.register_new_user(
        NEW_USER, "newbie", referrer_id=REF_OTHER)
    check("2-taklif: is_new=False", res2["is_new"] is False, str(res2))
    check("2-taklif: reward=0 (faqat birinchisi hisoblanadi)",
          res2["reward"] == 0, str(res2))
    check("2-taklif: referrer o'zgarmadi (hali REF_MAIN)",
          _ref(db_mod, NEW_USER) == REF_MAIN)
    check("2-taklif: REF_MAIN balansi o'zgarmadi (8)", _balance(db_mod, REF_MAIN) == 8)
    check("2-taklif: REF_OTHER bonus olmadi (5)", _balance(db_mod, REF_OTHER) == 5)
    check("2-taklif: yangi ledger yozuvi yo'q (1 qatorda qoladi)",
          len(_ledger(db_mod, REF_MAIN)) == 1 and _ledger(db_mod, REF_OTHER) == [])
    check("2-taklif: sabab 'already_referred'",
          res2["reason"] == "already_referred", str(res2))

    # 3-urinish: oldindan kirgan (referrersiz) foydalanuvchi keyinroq
    # havola orqali qaytadi — bu ham bonus bermaydi.
    db_mod.save_user(EXISTING, "old_user")  # referrer YO'Q
    res3 = ReferralService.register_new_user(
        EXISTING, "old_user", referrer_id=REF_MAIN)
    check("eski foydalanuvchi: is_new=False", res3["is_new"] is False, str(res3))
    check("eski foydalanuvchi: reward=0", res3["reward"] == 0, str(res3))
    check("eski foydalanuvchi: referrer hali ham yo'q",
          _ref(db_mod, EXISTING) is None)
    check("eski foydalanuvchi: sabab 'existing_user'",
          res3["reason"] == "existing_user", str(res3))
    check("eski foydalanuvchi: REF_MAIN balansi o'zgarmadi (8)",
          _balance(db_mod, REF_MAIN) == 8)

    # ------------------------------------------------------------
    print("== 8-bosqich (live): 3) LEDGER — to'liq audit (add + spend) ==")
    _ensure_user(db_mod, AUDIT_USER, credits=5)
    start_balance = 5

    r_add = CreditsService.add_credits(AUDIT_USER, 10, "promo", ref_id="PROMO100")
    check("add(+10 promo): success", r_add["success"] is True, str(r_add))
    check("add: balans 5→15", r_add["balance_after"] == 15
          and _balance(db_mod, AUDIT_USER) == 15)

    r_spend = CreditsService.spend_credits(AUDIT_USER, 2, "ai_request", ref_id="req-777")
    check("spend(-2 ai_request): success", r_spend["success"] is True, str(r_spend))
    check("spend: balans 15→13", r_spend["balance_after"] == 13
          and _balance(db_mod, AUDIT_USER) == 13)
    check("spend: qaytgan amount manfiy", r_spend["amount"] == -2)

    rows = _ledger(db_mod, AUDIT_USER)
    check("ledger: 2 qator (add + spend)", len(rows) == 2, str(rows))
    check("ledger: add qatori (+10, 15, promo, PROMO100)",
          rows[0]["amount"] == 10 and rows[0]["balance_after"] == 15
          and rows[0]["operation_type"] == "promo"
          and rows[0]["reference_id"] == "PROMO100", str(rows[0]))
    check("ledger: spend qatori (-2, 13, ai_request, req-777)",
          rows[1]["amount"] == -2 and rows[1]["balance_after"] == 13
          and rows[1]["operation_type"] == "ai_request"
          and rows[1]["reference_id"] == "req-777", str(rows[1]))

    hist = CreditsService.get_user_history(AUDIT_USER)
    check("history: 2 yozuv, eng yangisi birinchi",
          len(hist) == 2 and hist[0]["amount"] == -2 and hist[1]["amount"] == 10,
          str(hist))
    check("history: maydonlar to'liq",
          all(set(h) >= {"id", "user_id", "amount", "balance_after",
                         "operation_type", "reference_id", "created_at"}
              for h in hist))
    hist1 = CreditsService.get_user_history(AUDIT_USER, limit=1)
    check("history: limit=1 faqat so'nggini qaytaradi",
          len(hist1) == 1 and hist1[0]["amount"] == -2, str(hist1))

    # Kunlik streak: bonus ham ledger'da (op_type='daily_bonus').
    streak = db_mod.claim_daily_streak_bonus(AUDIT_USER)
    check("streak: bonus olindi", streak.get("success") is True, str(streak))
    check("streak: balans 13+1=14", _balance(db_mod, AUDIT_USER) == 14)
    rows = _ledger(db_mod, AUDIT_USER)
    check("streak: +1 daily_bonus yozuvi",
          rows[-1]["amount"] == 1 and rows[-1]["balance_after"] == 14
          and rows[-1]["operation_type"] == "daily_bonus", str(rows[-1]))
    # Streakni ikkinchi marta oldirish — bonus YO'Q (ledger o'smaydi).
    streak2 = db_mod.claim_daily_streak_bonus(AUDIT_USER)
    check("streak takror: bonus berilmadi",
          streak2.get("success") is False and _balance(db_mod, AUDIT_USER) == 14)
    check("streak takror: yangi ledger yozuvi yo'q (add+spend+streak=3)",
          len(_ledger(db_mod, AUDIT_USER)) == 3, str(len(_ledger(db_mod, AUDIT_USER))))

    # AI xatosidagi refund (add_user_credit) ham auditda.
    check("refund: add_user_credit True", db_mod.add_user_credit(AUDIT_USER) is True)
    rows = _ledger(db_mod, AUDIT_USER)
    check("refund: +1 ai_request yozuvi",
          rows[-1]["amount"] == 1 and rows[-1]["balance_after"] == 15
          and rows[-1]["operation_type"] == "ai_request", str(rows[-1]))

    check("audit zanjiri: barcha balance_after qiymatlari to'g'ri",
          _chain_ok(db_mod, AUDIT_USER, start_balance))

    # ------------------------------------------------------------
    print("== 8-bosqich (live): 4) BALANS YETARLISIG' — yechish bloklandi ==")
    _ensure_user(db_mod, POOR_USER, credits=5)
    try:
        CreditsService.spend_credits(POOR_USER, 6, "ai_request", ref_id="too-much")
        check("spend(6) bilan 5 ballda: InsufficientCreditsError", False)
    except InsufficientCreditsError as e:
        check("spend(6) bilan 5 ballda: InsufficientCreditsError", True)
        check("istisnoda aniq sonlar (kerak 6, mavjud 5)",
              e.required == 6 and e.available == 5, str(e))
    check("bloklangan yechish: balans o'zgarmadi (5)",
          _balance(db_mod, POOR_USER) == 5)
    check("bloklangan yechish: ledger yozuvi qolmadi",
          _ledger(db_mod, POOR_USER) == [])

    _ensure_user(db_mod, ZERO_USER, credits=0)
    check("use_user_credit(0 ball) → False", db_mod.use_user_credit(ZERO_USER) is False)
    check("use_user_credit(0 ball): balans 0 qoldi", _balance(db_mod, ZERO_USER) == 0)
    check("use_user_credit(0 ball): ledger yozuvi yo'q",
          _ledger(db_mod, ZERO_USER) == [])

    # Yetarli balansda esa normal yechiladi (AI Studio oqimi).
    check("use_user_credit(15 ball) → True", db_mod.use_user_credit(AUDIT_USER) is True)
    check("use_user_credit: balans 15→14", _balance(db_mod, AUDIT_USER) == 14)
    rows = _ledger(db_mod, AUDIT_USER)
    check("use_user_credit: -1 ai_request yozuvi",
          rows[-1]["amount"] == -1 and rows[-1]["operation_type"] == "ai_request",
          str(rows[-1]))

    # ------------------------------------------------------------
    print("== 8-bosqich (live): 5) PARALLEL yechish — double-spend yo'q ==")
    from concurrent.futures import ThreadPoolExecutor
    _ensure_user(db_mod, RACE_USER, credits=10)
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: db_mod.use_user_credit(RACE_USER),
                                range(20)))
    check("parallel: aynan 10 ta muvaffaqiyatli", sum(results) == 10, str(sum(results)))
    check("parallel: balans 0 ga tushdi", _balance(db_mod, RACE_USER) == 0)
    race_rows = _ledger(db_mod, RACE_USER)
    check("parallel: 10 ta ledger yozuvi", len(race_rows) == 10)
    check("parallel: balance_after zanjiri to'liq to'g'ri (9..0)",
          sorted(r["balance_after"] for r in race_rows) == list(range(0, 10)))
    # Ikkinchi marta urinilishi — hammasi False (ball qolmagan).
    again = [db_mod.use_user_credit(RACE_USER) for _ in range(3)]
    check("parallel: keyingi yechishlar bloklanadi", again == [False, False, False])
    check("parallel: qo'shimcha yozuv qo'shilmadi",
          len(_ledger(db_mod, RACE_USER)) == 10)

    # ------------------------------------------------------------
    print("== 8-bosqich (live): 6) ATOMIKLIK — yiqilishda hammasi ROLLBACK ==")
    _ensure_user(db_mod, ATOMIC_USER, credits=5)
    bal_before = _balance(db_mod, ATOMIC_USER)
    rows_before = len(_ledger(db_mod, ATOMIC_USER))
    try:
        with db_mod.db_transaction() as cur:
            # 1) ball yechiladi (muvaffaqiyatli)...
            CreditsService.spend_in_tx(cur, ATOMIC_USER, 1, "ai_request",
                                       ref_id="atomic-1")
            # 2) ...lekin tranzaksiya ichida xato yuz beradi →
            #    butun blok (balans + ledger) ROLLBACK bo'lishi shart.
            cur.execute(
                "INSERT INTO credits_ledger (user_id, amount, balance_after, "
                "operation_type) VALUES (%s, NULL, 0, 'promo')", (ATOMIC_USER,))
        check("atomiclik: tranzaksiya ROLLBACK bo'ldi", False)
    except psycopg2.IntegrityError:
        check("atomiclik: tranzaksiya ROLLBACK bo'ldi", True)
    check("atomiclik: balans o'zgarmadi", _balance(db_mod, ATOMIC_USER) == bal_before)
    check("atomiclik: ledger yozuvi qolmadi",
          len(_ledger(db_mod, ATOMIC_USER)) == rows_before)

    # Transfer: ikkala tomon uchun ham ledger yozuvi (op_type='transfer').
    # Eslatma: 3-kunlik xavfsizlik qoidasi — yangi hisob o'tkaza olmaydi,
    # shu sababli test userining created_at'ini 5 kun oldinga olib boramiz.
    _ensure_user(db_mod, POOR_USER, credits=10)
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute("UPDATE users SET created_at = NOW() - INTERVAL '5 days' "
                    "WHERE user_id = %s", (POOR_USER,))
    ok, msg = db_mod.transfer_user_credits(POOR_USER, AUDIT_USER, 5)
    check("transfer: muvaffaqiyatli", ok is True, msg)
    check("transfer: yuboruvchi 10→5", _balance(db_mod, POOR_USER) == 5)
    tr_rows = _ledger(db_mod, POOR_USER)
    last_out = tr_rows[-1] if tr_rows else None
    check("transfer: yuboruvchida -5 transfer yozuvi",
          last_out is not None and last_out["amount"] == -5
          and last_out["operation_type"] == "transfer"
          and last_out["reference_id"] == str(AUDIT_USER), str(last_out))
    tr_rows2 = _ledger(db_mod, AUDIT_USER)
    last_in = tr_rows2[-1] if tr_rows2 else None
    check("transfer: qabul qiluvchida +5 transfer yozuvi",
          last_in is not None and last_in["amount"] == 5
          and last_in["operation_type"] == "transfer"
          and last_in["reference_id"] == str(POOR_USER), str(last_in))


def run_live():
    uri = _live_uri()
    if not uri:
        print("== Real PostgreSQL (o'tkazib yuborildi) ==")
        skip("live 8-bosqich testlar", "(pgserver/URL mavjud emas)")
        return
    import database as db_mod
    db_mod.DATABASE_URL = uri
    os.environ["DATABASE_URL"] = uri
    db_mod._reset_pool()
    try:
        db_mod.init_db()
    except Exception as e:  # pragma: no cover - muhitga bog'liq
        skip("live 8-bosqich testlar", f"(PostgreSQL mavjud emas: {e})")
        return
    try:
        _cleanup(db_mod)
        test_live(db_mod)
    except Exception as e:  # pragma: no cover - xavfsizlik
        import traceback
        traceback.print_exc()
        check("live 8-bosqich testlari xatosiz o'tdi", False,
              f"{type(e).__name__}: {e}")
    finally:
        _cleanup(db_mod)
        db_mod.close_pool()


if __name__ == "__main__":
    test_static_schema()
    test_static_credits_service()
    test_static_referral_service()
    test_static_integration_wiring()
    run_live()

    print()
    if failures:
        print(f"O'tdi: {passed}, Xato: {failures}, O'tkazib yuborildi: {skipped}")
        print("8-bosqich testlarda xatolar bor ✗")
        sys.exit(1)
    print(f"O'tdi: {passed}, Xato: 0, O'tkazib yuborildi: {skipped}")
    print("Barcha 8-bosqich testlari muvaffaqiyatli o'tdi ✔")
