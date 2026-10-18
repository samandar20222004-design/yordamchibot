#!/usr/bin/env python3
"""OMMAGA CHIQARISHGA TAYYORLIK AUDITI (real PostgreSQL): obuna/Stars, bepul vs PRO qoidalari, bot nishoni.

Tekshiradi:
  1. Tarif katalogi: har tarif (8 ta) uchun Stars narxi invoice'da, precheckout'da va katalogda BIR XIL.
  2. Stars to'lovi (haqiqiy handler + haqiqiy DB): to'g'ri summa -> tarif/muddat; noto'g'ri summa/valyuta/foydalanuvchi -> BERILMAYDI;
     takroriy charge bir marta; muddat ustiga qo'shiladi; enterprise/ultra pasaymaydi; refund muddatni qaytaradi.
  3. Muddat tugashi: PRO limitlari bepulga tushadi.
  4. Bepul va PRO limitlari (kanal, navbat, kunlik AI) HAQIQIY tekshiruv funksiyalarida.
  5. «🤖 @bot» nishoni: bepulda HAR yuborish yo'lida (rejalangan, hozir yuborish, Magic/Score/Voice, Rasm->Post) bor,
     PRO/ULTRA/enterprise/admin da YO'Q; muddati o'tgan PRO da bor.

Faqat SINOV bazasi (URL bo'lmasa SKIP). Faqat o'z qatorlarini (user_id >= 9_700_000_000) yozadi va o'chiradi.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("MINIAPP_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "INTEGRITY_TEST_DATABASE_URL", server_dir="yordamchi_pg_release_audit")
if URL:
    os.environ["DATABASE_URL"] = URL
os.environ.setdefault("BOT_TOKEN", "123456789:TESTtokenABCDEFGHIJKLMNOPQRSTUV")
os.environ["ADMIN_ID"] = "111"
os.environ["ADMIN_IDS"] = "111,9700000006"  # ADMIN_U (config import'dan oldin)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

passed = failed = skipped = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [XATO] {label} {detail}")


BASE = 9_700_000_000
FREE, PRO, ULTRA, ENT, EXP, ADMIN_U, PAYER = (BASE + i for i in range(1, 8))
IDS = (FREE, PRO, ULTRA, ENT, EXP, ADMIN_U, PAYER)
CH = {u: f"-1009700{u - BASE:06d}" for u in IDS}


def main() -> int:
    global skipped
    if not URL:
        print("  [SKIP] release audit — BLOCKED: sinov bazasi URL berilmagan")
        skipped += 1
        return 0

    import psycopg2

    import config
    import database as db
    import scheduler
    from handlers import subscription as sub
    from locales.translations import get_text  # noqa: F401
    from services.payment_service import PaymentService  # noqa: F401
    from services.subscription_service import SubscriptionService

    db.init_db()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    run = loop.run_until_complete
    conn = psycopg2.connect(URL)
    conn.autocommit = True
    cur = conn.cursor()
    assert ADMIN_U in config.ADMIN_IDS_SET, config.ADMIN_IDS_SET
    BOT = config.BOT_USERNAME
    LINE = f"🤖 @{BOT}"

    def cleanup():
        cur.execute("DELETE FROM payments WHERE user_id = ANY(%s)", (list(IDS),))
        cur.execute("DELETE FROM scheduled_posts WHERE user_id = ANY(%s)", (list(IDS),))
        cur.execute("DELETE FROM channels WHERE user_id = ANY(%s)", (list(IDS),))
        cur.execute("DELETE FROM users WHERE user_id = ANY(%s)", (list(IDS),))

    def mkuser(uid, plan="free", expires=None):
        cur.execute("INSERT INTO users (user_id, username, full_name, language_code, plan_type, subscription_expires_at) "
                    "VALUES (%s,%s,%s,'uz',%s,%s) ON CONFLICT (user_id) DO UPDATE SET plan_type = EXCLUDED.plan_type, "
                    "subscription_expires_at = EXCLUDED.subscription_expires_at, ai_requests_today = 0",
                    (uid, f"u{uid}", f"N{uid}", plan, expires))

    def row(uid):
        cur.execute("SELECT plan_type, subscription_expires_at FROM users WHERE user_id = %s", (uid,))
        return cur.fetchone()

    now = datetime.now(timezone.utc)
    cleanup()
    try:
        # ------------------------------------------------------------------ 1
        print("\n== 1. Tarif katalogi va Stars narxlari ==")
        cat = config.TARIFF_CATALOG
        check("8 ta tarif: PRO 1m/3m/6m/1y va ULTRA u1m/u3m/u6m/u1y", set(cat) == {"1m", "3m", "6m", "1y", "u1m", "u3m", "u6m", "u1y"}, str(set(cat)))
        for key, info in cat.items():
            check(f"{key}: Stars katalogda == STARS_PLANS == INTL_STARS_AMOUNTS == invoice",
                  sub.STARS_PLANS[info["stars_key"]]["stars"] == info["stars"] == sub.INTL_STARS_AMOUNTS[key]
                  and sub.STARS_PLANS[info["stars_key"]]["days"] == info["days"] and sub.STARS_PLANS[info["stars_key"]]["tier"] == info["tier"],
                  f"{sub.STARS_PLANS.get(info['stars_key'])} vs {info}")
        for tier in ("pro", "ultra"):
            keys = [k for k, v in cat.items() if v["tier"] == tier]
            keys.sort(key=lambda k: cat[k]["days"])
            check(f"{tier}: uzoq muddat arzonroq (har oy narxi kamayadi)",
                  all(cat[b]["stars"] / cat[b]["months"] <= cat[a]["stars"] / cat[a]["months"] for a, b in zip(keys, keys[1:])))
        check("ULTRA PRO'dan qimmat (bir xil muddat uchun)", all(cat["u" + k]["stars"] > cat[k]["stars"] for k in ("1m", "3m", "6m", "1y")))

        invoices = []

        class InvBot:
            async def send_invoice(self, **kw):
                invoices.append(kw)

        for key, info in cat.items():
            invoices.clear()
            ok = run(sub._send_stars_invoice(SimpleNamespace(bot=InvBot()), 1, PAYER, key, "uz"))
            inv = invoices[0] if invoices else {}
            check(f"{key}: invoice XTR, {info['stars']} Stars, payload to'g'ri",
                  ok and inv.get("currency") == "XTR" and inv["prices"][0].amount == info["stars"]
                  and inv.get("payload") == f"sub_stars_{key}_{PAYER}", str(inv))

        # ------------------------------------------------------------------ 2
        print("\n== 2. Stars to'lovi: tekshiruv, berish, takrorlanish ==")
        for key, info in cat.items():
            p = f"sub_stars_{key}_{PAYER}"
            good, _ = sub._validate_stars_payload(p, PAYER, info["stars"], "XTR", "uz")
            bad_amt = sub._validate_stars_payload(p, PAYER, info["stars"] - 1, "XTR", "uz")[0]
            bad_amt2 = sub._validate_stars_payload(p, PAYER, info["stars"] + 1, "XTR", "uz")[0]
            bad_cur = sub._validate_stars_payload(p, PAYER, info["stars"], "USD", "uz")[0]
            bad_user = sub._validate_stars_payload(p, PAYER + 1, info["stars"], "XTR", "uz")[0]
            check(f"{key}: faqat aniq summa/valyuta/foydalanuvchi qabul", good and good["days"] == info["days"] and good["tier"] == info["tier"]
                  and bad_amt is None and bad_amt2 is None and bad_cur is None and bad_user is None)
        check("noma'lum tarif va xom payload rad", sub._validate_stars_payload(f"sub_stars_zz_{PAYER}", PAYER, 1, "XTR", "uz")[0] is None
              and sub._validate_stars_payload("hack", PAYER, 1, "XTR", "uz")[0] is None)

        replies, reports = [], []

        async def pay(uid, key, charge, amount=None, currency="XTR", payload=None):
            async def reply_text(text, **kw):
                replies.append(text)

            async def send_message(chat_id, text, **kw):
                reports.append((chat_id, text))

            payment = SimpleNamespace(total_amount=cat[key]["stars"] if amount is None else amount, currency=currency,
                                      invoice_payload=payload or f"sub_stars_{key}_{uid}", telegram_payment_charge_id=charge)
            upd = SimpleNamespace(message=SimpleNamespace(successful_payment=payment, reply_text=reply_text),
                                  effective_user=SimpleNamespace(id=uid))
            ctx = SimpleNamespace(user_data={"lang": "uz"}, bot=SimpleNamespace(send_message=send_message))
            await sub.successful_payment_callback(upd, ctx)

        mkuser(PAYER)
        run(pay(PAYER, "1m", "ch-a-1"))
        plan, exp = row(PAYER)
        check("bepul + PRO 1 oy -> pro, ~30 kun", plan == "pro" and exp and 29.9 < (exp - now).total_seconds() / 86400 < 30.1, f"{plan} {exp}")
        first_exp = exp
        run(pay(PAYER, "1m", "ch-a-1"))
        check("bir xil charge qayta kelsa — muddat ikki marta qo'shilmaydi", row(PAYER)[1] == first_exp)
        cur.execute("SELECT COUNT(*), MIN(amount), MIN(currency), MIN(status) FROM payments WHERE user_id = %s", (PAYER,))
        cnt, amt, curc, st = cur.fetchone()
        check("payments: 1 ta qator, katalogdagi Stars, XTR, succeeded", (cnt, amt, curc, st) == (1, cat["1m"]["stars"], "XTR", "succeeded"), str((cnt, amt, curc, st)))
        run(pay(PAYER, "3m", "ch-a-2"))
        plan, exp = row(PAYER)
        check("faol PRO ustiga 3 oy -> muddat +90 kun qo'shiladi (kuymaydi)", plan == "pro" and abs((exp - first_exp).total_seconds() / 86400 - 90) < 0.1, f"{exp - first_exp}")
        before = row(PAYER)
        reports.clear()
        run(pay(PAYER, "1m", "ch-bad-1", amount=1))
        run(pay(PAYER, "1m", "ch-bad-2", currency="USD"))
        run(pay(PAYER, "1m", "ch-bad-3", payload=f"sub_stars_1m_{PAYER + 5}"))
        cur.execute("SELECT COUNT(*) FROM payments WHERE telegram_payment_charge_id LIKE 'ch-bad-%%'")
        bad_rows = cur.fetchone()[0]
        check("noto'g'ri summa/valyuta/egasi — PRO berilmaydi, payments yozilmaydi", row(PAYER) == before and bad_rows == 0)
        check("rad etilgan to'lov adminlarga ogohlantirildi (jim qolmaydi)", len(reports) >= 3, str(reports))
        run(pay(PAYER, "u1m", "ch-a-3"))
        check("PRO faol + ULTRA to'lov -> ultra", row(PAYER)[0] == "ultra", str(row(PAYER)))
        ultra_exp = row(PAYER)[1]
        run(pay(PAYER, "1m", "ch-a-4"))
        plan, exp = row(PAYER)
        check("faol ULTRA ustiga PRO to'lov — ULTRA'dan PRO'ga TUSHMAYDI, muddat qo'shiladi", plan == "ultra" and exp > ultra_exp, str(row(PAYER)))
        mkuser(ENT, "enterprise", None)
        run(pay(ENT, "1m", "ch-e-1"))
        check("enterprise (muddatsiz) to'lovdan keyin ham enterprise/muddatsiz", row(ENT) == ("enterprise", None), str(row(ENT)))

        print("\n== 2b. Refund ==")
        mkuser(PAYER)
        run(pay(PAYER, "1m", "ch-r-1"))
        cur.execute("SELECT subscription_expires_at FROM users WHERE user_id = %s", (PAYER,))
        r1 = db.refund_stars_payment("ch-r-1")
        plan, exp = row(PAYER)
        check("refund: to'lov bergan 30 kun ayrildi -> bepul", r1["result"] == "revoked" and plan == "free", f"{r1} {row(PAYER)}")
        check("refund takrorlansa 'already' (ikki marta ayrilmaydi)", db.refund_stars_payment("ch-r-1")["result"] == "already")
        check("noma'lum charge 'unknown_charge'", db.refund_stars_payment("nope")["result"] == "unknown_charge")
        run(pay(ENT, "3m", "ch-e-2"))
        db.refund_stars_payment("ch-e-2")
        check("enterprise refunddan zarar ko'rmaydi", row(ENT) == ("enterprise", None))

        # ------------------------------------------------------------------ 3
        print("\n== 3. Muddat tugashi ==")
        mkuser(EXP, "pro", now - timedelta(days=1))
        check("muddati o'tgan PRO is_premium=False", SubscriptionService.is_premium(EXP) is False)
        check("... va bazada 'free' ga tushdi", row(EXP)[0] == "free")
        mkuser(EXP, "pro", now - timedelta(hours=1))
        ok_ch, cnt_ch, max_ch = db.check_channel_limit(EXP)
        check("muddati o'tgan PRO kanal limiti = bepul limit", max_ch == config.TIER_LIMITS["free"]["max_channels"], str((ok_ch, cnt_ch, max_ch)))
        mkuser(EXP, "pro", now + timedelta(days=5))
        check("muddati o'tmagan PRO faol", SubscriptionService.is_premium(EXP) is True)
        mkuser(EXP, "pro", now - timedelta(minutes=5))
        n = db.downgrade_expired_subscriptions()
        check("kunlik tozalash (sweep) muddati o'tganlarni tushiradi", n >= 1 and row(EXP)[0] == "free")

        # ------------------------------------------------------------------ 4
        print("\n== 4. Bepul va PRO limitlari (haqiqiy tekshiruvlar) ==")
        mkuser(FREE)
        mkuser(PRO, "pro", now + timedelta(days=20))
        mkuser(ULTRA, "ultra", now + timedelta(days=20))
        lim = config.TIER_LIMITS
        for uid, tier in ((FREE, "free"), (PRO, "pro"), (ULTRA, "ultra")):
            can, cnt_c, mx = db.check_channel_limit(uid)
            check(f"{tier}: kanal limiti = {lim[tier]['max_channels']}", mx == lim[tier]["max_channels"] and can and cnt_c == 0, str((can, cnt_c, mx)))
            can_q, cnt_q, mq = db.check_queue_limit(uid)
            check(f"{tier}: navbat limiti = {lim[tier]['queued_posts']}", mq == lim[tier]["queued_posts"] and can_q, str((can_q, cnt_q, mq)))
        # Bepul: kanal limitiga yetgach rad
        for i in range(lim["free"]["max_channels"]):
            cur.execute("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES (%s,%s,'x',TRUE)", (FREE, f"-1009700900{i}"))
        check("bepul: kanal limitiga yetgach YANGI kanal rad", db.check_channel_limit(FREE)[0] is False)
        for i in range(lim["free"]["max_channels"]):
            cur.execute("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES (%s,%s,'x',TRUE)", (PRO, f"-1009700910{i}"))
        check("PRO: bepul limit (3) dan ko'p kanal qo'sha oladi", db.check_channel_limit(PRO)[0] is True)
        cur.execute("INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, scheduled_time, status) "
                    "SELECT %s, '-10097009000', 'text', 'x', NOW() + INTERVAL '1 day', 'pending' FROM generate_series(1, %s)",
                    (FREE, lim["free"]["queued_posts"]))
        check("bepul: navbat to'lgach rad", db.check_queue_limit(FREE)[0] is False)
        cur.execute("INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, scheduled_time, status) "
                    "SELECT %s, '-10097009100', 'text', 'x', NOW() + INTERVAL '1 day', 'pending' FROM generate_series(1, %s)",
                    (PRO, lim["free"]["queued_posts"]))
        check("PRO: bepul navbatdan ko'p post qo'sha oladi", db.check_queue_limit(PRO)[0] is True)
        free_ai = lim["free"]["daily_ai_requests"]
        res = [db.check_ai_limit(FREE)[0] for _ in range(free_ai + 2)]
        check(f"bepul: kuniga {free_ai} ta AI, keyingisi rad", res[:free_ai] == [True] * free_ai and res[free_ai:] == [False, False], str(res))
        res = [db.check_ai_limit(PRO)[0] for _ in range(free_ai + 2)]
        check("PRO: bepul AI limitidan keyin ham davom etadi", all(res))

        # ------------------------------------------------------------------ 5
        print("\n== 5. «🤖 @bot» nishoni ==")
        mkuser(ENT, "enterprise", None)
        mkuser(ADMIN_U, "free")
        mkuser(EXP, "pro", now - timedelta(hours=2))
        users = {"bepul": (FREE, True), "PRO": (PRO, False), "ULTRA": (ULTRA, False), "enterprise": (ENT, False),
                 "admin": (ADMIN_U, False), "muddati o'tgan PRO": (EXP, True)}

        def payload_for(uid, ptype, content="Salom, yangilik!"):
            ctx = {"post_id": 1, "user_id": uid, "channel_id": CH[uid], "post_type": ptype, "content": content, "btn_text": None,
                   "btn_url": None, "enable_reactions": False, "reaction_emojis": None}
            return run(scheduler._build_send_payload(ctx))

        for ptype in ("text", "photo", "video", "animation", "document", "album"):
            for name, (uid, expect) in users.items():
                out = payload_for(uid, ptype)
                text = (out or {}).get("final_content") or ""
                has = text.lstrip().startswith(LINE) and text.count(LINE) == 1
                none = LINE not in text
                check(f"rejalangan [{ptype}] {name}: nishon {'BOR, POST BOSHIDA (1 marta)' if expect else 'YO`Q'}", has if expect else none, text[:80])
        long_text = "a" * 5000
        out = payload_for(FREE, "text", long_text)["final_content"]
        check("bepul: 5000 belgili matn kesilganda ham nishon saqlanadi", LINE in out and len(out) <= 4096 + 40, str(len(out)))
        out = payload_for(FREE, "photo", "b" * 3000)["final_content"]
        check("bepul: rasm izohi (1024) kesilganda ham nishon saqlanadi", LINE in out and len(out) <= 1100, str(len(out)))
        check("bepul: bo'sh matnli postda ham nishon bor", LINE in payload_for(FREE, "photo", "")["final_content"])

        print("\n== 5b. To'g'ridan-to'g'ri yuborish yo'llari ==")
        from handlers import image_post, magic_post, post_score, voice_post
        for label, mod, fn_name, key in (("Magic Post", magic_post, "_magic_finish_send", "magic_post_text"),
                                         ("Post Score", post_score, "_finish_send", "ps_post"),
                                         ("Voice Post", voice_post, "_voice_finish_send", "voice_post_text")):
            for name, (uid, expect) in users.items():
                sent = []

                async def fake_send_message(bot, chat_id, text="", **kw):
                    sent.append(text)
                    return SimpleNamespace(message_id=1)

                saved = magic_post.delivery_service.send_message
                magic_post.delivery_service.send_message = fake_send_message
                query = SimpleNamespace(from_user=SimpleNamespace(id=uid), edit_message_text=AsyncMock(), answer=AsyncMock(),
                                        message=SimpleNamespace(reply_text=AsyncMock(), chat_id=uid))
                context = SimpleNamespace(user_data={"lang": "uz", key: "Salom, dunyo!", "ps_text": "Salom, dunyo!"},
                                          bot=SimpleNamespace(send_message=AsyncMock()))
                try:
                    run(getattr(mod, fn_name)(query, context, [(CH[uid], "Kanal")]))
                except Exception as exc:  # noqa: BLE001
                    sent.append(f"EXC {type(exc).__name__}: {exc}")
                finally:
                    magic_post.delivery_service.send_message = saved
                text = sent[0] if sent else ""
                has = text.lstrip().startswith(LINE)
                check(f"{label} -> kanal, {name}: nishon {'BOR' if expect else 'YO`Q'}", has if expect else (not has and bool(text) and not text.startswith("EXC")),
                      text[:100])

        for name, (uid, expect) in users.items():
            captured = {}

            async def fake_photo(bot, **kw):
                captured["caption"] = kw.get("caption", "")
                return SimpleNamespace(message_id=1)

            saved = image_post.delivery_service.send_photo
            image_post.delivery_service.send_photo = fake_photo
            query = SimpleNamespace(from_user=SimpleNamespace(id=uid), edit_message_text=AsyncMock(), answer=AsyncMock(),
                                    message=SimpleNamespace(reply_text=AsyncMock(), chat_id=uid))
            context = SimpleNamespace(user_data={"lang": "uz", "image_post_file_id": "FILE", "image_post_text": "Rasm matni"},
                                      bot=SimpleNamespace())
            try:
                run(image_post._deliver_targets(query, context, [(CH[uid], "Kanal")]))
            except Exception as exc:  # noqa: BLE001
                captured["caption"] = f"EXC {type(exc).__name__}: {exc}"
            finally:
                image_post.delivery_service.send_photo = saved
            cap = captured.get("caption", "")
            check(f"Rasm->Post -> kanal, {name}: nishon {'BOR' if expect else 'YO`Q'}", cap.lstrip().startswith(LINE) if expect else (LINE not in cap and "Rasm matni" in cap), cap[:100])
    finally:
        cleanup()
        conn.close()
    print(f"\nNATIJA: [OK]={passed} [XATO]={failed} [SKIP]={skipped}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
