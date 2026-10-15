#!/usr/bin/env python3
"""To'lov oqimidagi ochiq bandlar (AUDIT-007, P-1, P-2): regressiya testi (Payme — xotira do'koni; qolganlari real PostgreSQL).

* P-2: Payme PerformTransaction foydalanuvchi qatori yo'q bo'lsa PRO'siz "to'langan" qilmaydi — tranzaksiya bekor, pul olinmaydi;
* AUDIT-007: bir xil chek rasmi (file_unique_id) topiladi, kutayotgan cheklar soni to'g'ri sanaladi, takror RAD ETILMAYDI;
* P-1: «rasm bilan PRO» tasdig'i bir foydalanuvchiga bir kunda bir marta (atomik), muvaffaqiyatsizlikda qaytariladi;
* yangi matnlar uz/ru/en tillarida.
"""
from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("INTEGRITY_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "MINIAPP_TEST_DATABASE_URL", server_dir="yordamchi_pg_paygaps")
if URL:
    os.environ["DATABASE_URL"] = URL
os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [XATO] {label} {detail}")


print("== To'lov bandlari ==")

# --- i18n ---
from locales.translations import TRANSLATIONS  # noqa: E402

for key in ("receipt_admin_duplicate_line", "receipt_too_many_pending", "pc_already_decided", "stars_refund_user"):
    check(f"i18n: {key} uch tilda bor va farq qiladi",
          all(TRANSLATIONS[l].get(key) for l in ("uz", "ru", "en")) and len({TRANSLATIONS[l][key] for l in ("uz", "ru", "en")}) == 3)

# --- P-2: Payme (xotira do'koni) ---
from payme_merchant_test import (  # noqa: E402
    CONFIG, ERR_CANNOT_PERFORM, STATE_CREATED, create_params, err_code, make_provider, rpc,
)
from services.payments import memory_store  # noqa: E402

provider, store, clock, order = make_provider(CONFIG)
rpc(provider, "CreateTransaction", create_params(order))
orig = memory_store._MemoryUnitOfWork.grant_subscription
memory_store._MemoryUnitOfWork.grant_subscription = lambda self, user_id, days: False  # foydalanuvchi qatori yo'q
try:
    resp, _ = rpc(provider, "PerformTransaction", {"id": "6630a1b2c3d4e5f600000001"})
finally:
    memory_store._MemoryUnitOfWork.grant_subscription = orig
tx = store.transactions["6630a1b2c3d4e5f600000001"]
check("P-2: foydalanuvchi qatori yo'q -> 'bajarib bo'lmaydi' (-31008)", err_code(resp) == ERR_CANNOT_PERFORM, str(resp))
check("P-2: tranzaksiya 'performed' bo'lmadi, ledger bo'sh, buyurtma pending",
      tx.state == STATE_CREATED and not store.ledger and store.orders[order.order_id].status == "pending", f"{tx.state} {store.ledger}")
resp, _ = rpc(provider, "PerformTransaction", {"id": "6630a1b2c3d4e5f600000001"})
check("P-2: foydalanuvchi paydo bo'lgach qayta urinish muvaffaqiyatli, PRO bir marta", (resp.get("result") or {}).get("state") == 2 and len(store.grants) == 1, str(resp))

if not URL:
    print("  [SKIP] real PostgreSQL URL yo'q (cheklar va photo_check qismi)")
    print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=1")
    sys.exit(0 if failed == 0 else 1)

import database as db  # noqa: E402

db.DATABASE_URL = URL
db._reset_pool()
db.init_db()
U1, U2 = 9_500_000_051, 9_500_000_052


def q(sql, params=()):
    with db.db_cursor(commit=True) as cur:
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except Exception:  # noqa: BLE001
            return []


def cleanup():
    q("DELETE FROM payment_receipts WHERE user_id = ANY(%s)", ([U1, U2],))
    q("DELETE FROM system_settings WHERE key LIKE %s OR key LIKE %s", (f"photocheck_grant:{U1}:%", f"photocheck_grant:{U2}:%"))


cleanup()
try:
    # --- AUDIT-007 ---
    r1 = db.save_payment_receipt(U1, "photo", "FILE-A", "", "u1", "N1", "uz", 30, amount_uzs=19000, file_unique_id="UNIQ-X")
    check("chek file_unique_id bilan saqlandi", r1 and q("SELECT file_unique_id FROM payment_receipts WHERE id=%s", (r1,))[0][0] == "UNIQ-X")
    check("birinchi chekda takror yo'q", db.find_duplicate_receipts("UNIQ-X", r1) == [])
    r2 = db.save_payment_receipt(U2, "photo", "FILE-B", "", "u2", "N2", "uz", 30, amount_uzs=19000, file_unique_id="UNIQ-X")
    dups = db.find_duplicate_receipts("UNIQ-X", r2)
    check("ikkinchi foydalanuvchining shu rasmi: takror topildi (id, user, holat)", r2 and [d["id"] for d in dups] == [r1] and dups[0]["user_id"] == U1 and dups[0]["status"] == "pending", str(dups))
    check("takror RAD ETILMADI (ikkinchi chek saqlandi, pending)", q("SELECT status FROM payment_receipts WHERE id=%s", (r2,))[0][0] == "pending")
    check("unique id bo'sh -> takror izlanmaydi", db.find_duplicate_receipts("", 0) == [] and db.find_duplicate_receipts(None, 0) == [])
    r3 = db.save_payment_receipt(U1, "photo", "FILE-C", "", "u1", "N1", "uz", 30, amount_uzs=19000)
    check("file_unique_id'siz (eski chaqiruv) ham ishlaydi", r3 > 0)
    check("kutayotgan cheklar soni: U1=2, U2=1", db.count_user_pending_receipts(U1) == 2 and db.count_user_pending_receipts(U2) == 1)
    q("UPDATE payment_receipts SET status='approved' WHERE id=%s", (r1,))
    check("ko'rilgan chek kutayotganlarga kirmaydi (U1=1)", db.count_user_pending_receipts(U1) == 1)
    check("foydalanuvchisiz/xatoda 0", db.count_user_pending_receipts(0) == 0)

    # --- P-1 ---
    check("photo_check: birinchi tasdiq huquqi beriladi", db.claim_photo_check_grant(U1) is True)
    check("photo_check: ikkinchi admin/qayta bosish rad (bir kunda bir marta)", db.claim_photo_check_grant(U1) is False)
    check("photo_check: boshqa foydalanuvchi mustaqil", db.claim_photo_check_grant(U2) is True)
    db.release_photo_check_grant(U1)
    check("photo_check: PRO berilmasa huquq qaytariladi (qayta bosish mumkin)", db.claim_photo_check_grant(U1) is True)
finally:
    cleanup()

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
