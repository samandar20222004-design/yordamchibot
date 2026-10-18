#!/usr/bin/env python3
"""Mintaqa/so'm narxi (real PostgreSQL): +998 tasdiqlash, eski mahalliy mijoz, ko'rinish tanlovi, Mini App `pay_region`.

Faqat SINOV bazasi (URL bo'lmasa SKIP). Faqat o'z qatorlarini (user_id >= 9_800_000_000) yozadi va o'chiradi.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("MINIAPP_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "INTEGRITY_TEST_DATABASE_URL", server_dir="yordamchi_pg_regional")
if URL:
    os.environ["DATABASE_URL"] = URL
os.environ.setdefault("BOT_TOKEN", "123456789:TESTtokenABCDEFGHIJKLMNOPQRSTUV")
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


A, B, C, D, E = (9_800_000_000 + i for i in range(1, 6))
IDS = (A, B, C, D, E)


def main() -> int:
    if not URL:
        print("  [SKIP] regional_pricing_db — BLOCKED: sinov bazasi URL berilmagan")
        return 0
    import psycopg2

    import database as db
    from miniapp_api import repository as mrepo
    from miniapp_api.service import pay_region

    db.init_db()
    conn = psycopg2.connect(URL)
    conn.autocommit = True
    cur = conn.cursor()

    def cleanup():
        cur.execute("DELETE FROM payments WHERE user_id = ANY(%s)", (list(IDS),))
        cur.execute("DELETE FROM users WHERE user_id = ANY(%s)", (list(IDS),))

    def mk(uid, lang="uz"):
        cur.execute("INSERT INTO users (user_id, username, full_name, language_code, plan_type) VALUES (%s,%s,%s,%s,'free') "
                    "ON CONFLICT (user_id) DO UPDATE SET uz_verified = FALSE, pay_region = NULL", (uid, f"u{uid}", f"N{uid}", lang))

    cleanup()
    try:
        for uid, lang in ((A, "uz"), (B, "en"), (C, "ru"), (D, "uz"), (E, "uz")):
            mk(uid, lang)
        print("\n== Til mintaqani BELGILAMAYDI ==")
        check("yangi foydalanuvchi: o'zbek tilida ham 'intl' (dollar)", db.get_pay_region(A) == "intl" and db.get_pay_region(D) == "intl")
        check("ru/en ham 'intl'", db.get_pay_region(B) == "intl" and db.get_pay_region(C) == "intl")
        check("noma'lum foydalanuvchi: 'intl' (xavfsiz tomon)", db.get_pay_region(9_800_000_099) == "intl")
        check("tasdiqlanmagan so'm tanlay olmaydi (set_pay_region('uz') -> False)", db.set_pay_region(A, "uz") is False and db.get_pay_region(A) == "intl")
        check("noto'g'ri mintaqa rad etiladi", db.set_pay_region(A, "mars") is False)

        print("\n== +998 tasdiqlash ==")
        check("o'z +998 kontakti qabul qilinadi", db.verify_uz_phone(A, "+998 90 123-45-67", A) is True)
        check("tasdiqlangach 'uz' (so'm)", db.get_pay_region(A) == "uz" and db.is_uz_eligible(A) is True)
        check("BOSHQA odamning kontakti rad etiladi", db.verify_uz_phone(B, "+998901234567", A) is False and db.is_uz_eligible(B) is False)
        check("kontakt user_id yo'q/noto'g'ri rad etiladi", db.verify_uz_phone(B, "+998901234567", None) is False
              and db.verify_uz_phone(B, "+998901234567", "x") is False)
        for bad in ("+79001234567", "+1 415 555 2671", "998901234", "+99890123456789", "", None, "abc"):
            check(f"chet el/noto'g'ri raqam rad: {bad!r}", db.verify_uz_phone(B, bad, B) is False)
        check("rad etilganlardan keyin B hamon 'intl'", db.get_pay_region(B) == "intl")
        cur.execute("SELECT uz_verified FROM users WHERE user_id = %s", (A,))
        check("raqamning o'zi SAQLANMAGAN (faqat belgi)", cur.fetchone()[0] is True
              and not any("998901234567" in str(v) for v in (cur.execute("SELECT row_to_json(u) FROM users u WHERE user_id = %s", (A,)), cur.fetchone())[1:]))

        print("\n== Ko'rinish tanlovi ==")
        check("tasdiqlangan dollarni tanlay oladi", db.set_pay_region(A, "intl") is True and db.get_pay_region(A) == "intl")
        check("... va qayta so'mga o'ta oladi (qayta tasdiqlash shart emas)", db.set_pay_region(A, "uz") is True and db.get_pay_region(A) == "uz")

        print("\n== Eski mahalliy mijoz (karta/Payme orqali to'lagan) ==")
        check("to'lovsiz D: 'intl'", db.get_pay_region(D) == "intl")
        cur.execute("INSERT INTO payments (user_id, amount, currency, payload, telegram_payment_charge_id, status, payment_method) "
                    "VALUES (%s, 29000, 'UZS', 'x', %s, 'succeeded', 'uzcard_humo')", (D, f"loc-{D}"))
        check("mahalliy to'lagan D: avtomatik 'uz' (qayta tasdiqlamaydi)", db.get_pay_region(D) == "uz" and db.is_uz_eligible(D) is True)
        cur.execute("INSERT INTO payments (user_id, amount, currency, payload, telegram_payment_charge_id, status, payment_method) "
                    "VALUES (%s, 195, 'XTR', 'x', %s, 'succeeded', 'international_stars')", (E, f"xtr-{E}"))
        check("Stars to'lagan E: mahalliy EMAS -> 'intl'", db.get_pay_region(E) == "intl" and db.is_uz_eligible(E) is False)
        cur.execute("INSERT INTO payments (user_id, amount, currency, payload, telegram_payment_charge_id, status, payment_method) "
                    "VALUES (%s, 29000, 'UZS', 'x', %s, 'refunded', 'uzcard_humo')", (E, f"ref-{E}"))
        check("qaytarilgan mahalliy to'lov hisobga olinmaydi", db.is_uz_eligible(E) is False)

        print("\n== Mini App ==")
        cur2 = conn.cursor()
        acc = {uid: mrepo.load_account(cur2, uid) for uid in (A, B, D)}
        check("Mini App: tasdiqlangan A -> 'uz'; B -> 'intl'; mahalliy to'lagan D -> 'uz'",
              pay_region(acc[A]) == "uz" and pay_region(acc[B]) == "intl" and pay_region(acc[D]) == "uz",
              str({k: (v or {}).get("uz_eligible") for k, v in acc.items()}))
        db.set_pay_region(A, "intl")
        check("Mini App: A dollarni tanlasa 'intl'", pay_region(mrepo.load_account(cur2, A)) == "intl")
    finally:
        cleanup()
        conn.close()
    print(f"\nNATIJA: [OK]={passed} [XATO]={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
