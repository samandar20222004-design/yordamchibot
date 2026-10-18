#!/usr/bin/env python3
"""🛡 Reklama birjasi xavfsizligi: firibgarlik skaneri, spam, global ban, shikoyat, o'qilmagan hisobi, bot va Mini App oqimi.

Sof qism (skaner) DB'siz; real PG qismi URL bo'lmasa SKIP. Faqat o'z qatorlarini (user_id >= 9_600_000_000) yozadi.
"""
from __future__ import annotations

import asyncio
import os
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("INTEGRITY_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "MINIAPP_TEST_DATABASE_URL", server_dir="yordamchi_pg_market_safety")
if URL:
    os.environ["DATABASE_URL"] = URL
os.environ.setdefault("BOT_TOKEN", "123456:MARKET_SAFETY_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
warnings.filterwarnings("ignore")
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


from services import market_safety as safety  # noqa: E402
from translations import market_t  # noqa: E402

print("== Skaner (sof mantiq) ==")
A = safety.assess
check("oddiy reklama so'rovi: toza", A("Salom, 1 ta post reklama kerak, byudjet 100 000 so'm")["flags"] == [] and A("Salom, 1 ta post reklama kerak")["ok"])
check("karta raqami to'siladi (bo'shliq/chiziq bilan ham)", A("8600 1234 5678 9012")["reason"] == "card" and A("9860-1234-5678-9012")["reason"] == "card"
      and A("karta 8600123456789012")["reason"] == "card")
check("telefon/narx/oddiy sonlar karta emas", A("+998 90 123 45 67")["ok"] and A("Narx 1 500 000 so'm")["ok"] and A("12 ta post, 300 000")["ok"])
check("kripto hamyon (TRC20/ERC20/BTC) to'siladi", A("TJRabPrwbZy45PuZNJbaDDNDBmbZPsbJy5")["reason"] == "wallet"
      and A("0x" + "a1" * 20)["reason"] == "wallet" and A("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")["reason"] == "wallet")
check("birinchi xabarda havola to'siladi", A("https://bit.ly/x", first_message=True)["reason"] == "link" and A("t.me/kanal", first_message=True)["reason"] == "link")
check("yangi hisob (<2 kun) havola yubora olmaydi, eski hisob — faqat ogohlantirish",
      A("www.site.com", account_age_days=0.2)["reason"] == "link" and (lambda r: r["ok"] and "link" in r["flags"])(A("www.site.com", account_age_days=30)))
check("kanal egasi o'z kanali havolasini yubora oladi", (lambda r: r["ok"])(A("t.me/mychannel", first_message=True, owner_sender=True)))
check("oldindan to'lov so'rovi belgilanadi (3 tilda)", "prepay" in A("Oldindan to'lov qiling")["flags"] and "prepay" in A("Нужна предоплата")["flags"]
      and "prepay" in A("Please send money first")["flags"])
check("shoshiltirish + oldindan to'lov = yuqori xavf", A("Oldindan to'lov qiling, shoshiling!")["risk"] == "high")
check("«kafolatlangan daromad/kripto» shubhali ibora", "scam" in A("100% kafolat, kripto investitsiya")["flags"])
check("apostrof/nol-kenglik hiylasi (o‌ldindan) ishlamaydi", "prepay" in A("oldin​dan to‘lov qiling")["flags"] or "prepay" in A("oldindan to`lov")["flags"])
check("flags pack/unpack va ogohlantirish kalitlari tartibi", safety.unpack_flags(safety.pack_flags(["pressure", "prepay", "prepay"])) == ["prepay", "pressure"]
      and safety.warning_keys(["pressure", "link", "prepay"]) == ["prepay", "pressure", "link"])
check("takroriy-matn normallashtirish", safety.normalize_for_dup("  Salom   DUNYO ") == "salom dunyo")
check("ogohlantirish matnlari uz/ru/en mavjud va bo'sh emas", all(market_t(k, lang) and market_t(k, lang) != k
      for k in ("mk_warn_prepay", "mk_warn_scam", "mk_warn_pressure", "mk_warn_link", "mk_unsafe_card", "mk_unsafe_wallet", "mk_unsafe_link", "mk_banned")
      for lang in ("uz", "ru", "en")))

print("\n== Real PostgreSQL: spam, ban, shikoyat, o'qilmagan ==")
if not URL:
    skipped += 1
    print("  [SKIP] real PostgreSQL URL yo'q")
    print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip={skipped}")
    sys.exit(1 if failed else 0)

import database as db  # noqa: E402
from repositories import ad_market_repository as repo  # noqa: E402
from services import ad_market as svc  # noqa: E402

db.DATABASE_URL = URL
db._reset_pool()
db.init_db()

OWN, ADV, ADV2, ADV3, ADV4, OWN2 = 9_600_000_001, 9_600_000_002, 9_600_000_003, 9_600_000_004, 9_600_000_005, 9_600_000_006
USERS = (OWN, ADV, ADV2, ADV3, ADV4, OWN2)
CH, CH2 = "-100960000001", "-100960000002"


def q(sql, params=()):
    with db.db_cursor(commit=True) as cur:
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except Exception:  # noqa: BLE001
            return []


def cleanup():
    q("DELETE FROM ad_market_listings WHERE owner_id = ANY(%s)", (list(USERS),))
    q("DELETE FROM ad_market_bans WHERE user_id = ANY(%s)", (list(USERS),))
    q("DELETE FROM ad_market_user_reports WHERE reporter_id = ANY(%s) OR reported_id = ANY(%s)", (list(USERS), list(USERS)))
    q("DELETE FROM ad_market_blocks WHERE owner_id = ANY(%s)", (list(USERS),))
    q("DELETE FROM channels WHERE channel_id = ANY(%s)", ([CH, CH2],))
    q("DELETE FROM users WHERE user_id = ANY(%s)", (list(USERS),))


cleanup()
try:
    for uid in USERS:
        q("INSERT INTO users (user_id, username, plan_type) VALUES (%s, %s, 'free')", (uid, f"s{uid}"))
    q("UPDATE users SET created_at = NOW() - INTERVAL '30 days' WHERE user_id = ANY(%s)", ([OWN, ADV, ADV2, ADV3, OWN2],))
    # ADV4 — hozirgina ro'yxatdan o'tgan (yangi hisob)
    q("INSERT INTO channels (user_id, channel_id, channel_title) VALUES (%s,%s,'Bir'),(%s,%s,'Ikki')", (OWN, CH, OWN2, CH2))
    L1 = repo.create_listing(OWN, CH, "safe1", "Xavfsiz", "tech", 1000, None)["listing_id"]
    L2 = repo.create_listing(OWN2, CH2, "safe2", "Ikkinchi", "news", 1000, None)["listing_id"]

    age_old, age_new = repo.get_account_age_days(ADV), repo.get_account_age_days(ADV4)
    check("hisob yoshi: eski ~30 kun, yangi < 1 kun", 29 < age_old < 31 and age_new < 1, f"{age_old} {age_new}")
    v = svc.screen_message(ADV4, "Salom, saytga qarang: www.site.com", first_message=False, owner_sender=False)
    check("yangi hisob havola yubora olmaydi (DB'dan yosh olinadi)", not v["ok"] and v["reason"] == "link")
    v = svc.screen_message(ADV, "Salom, saytga qarang: www.site.com", first_message=False, owner_sender=False)
    check("eski hisob havola yuboradi, lekin belgilanadi", v["ok"] and "link" in v["flags"] and v["packed"] == "link")
    ctx = svc.peer_context(ADV4)
    check("peer_context: yangi hisob nishoni", ctx["new_account"] is True and ctx["age_days"] == 0)
    check("trust_text yangi hisob uchun ogohlantiradi", "Yangi foydalanuvchi" in svc.trust_text(ctx, "uz") and svc.trust_text({"new_account": False, "reports": 0}, "uz") == "")

    r = repo.create_inquiry(L1, ADV, "Oldindan to'lov qilaman, shoshiling", "prepay,pressure")
    I1 = r["inquiry_id"]
    check("so'rov flags bilan saqlandi", r["ok"] and q("SELECT flags FROM ad_market_messages WHERE inquiry_id = %s", (I1,))[0][0] == "prepay,pressure")
    check("xabarlarda flags qaytadi (oluvchi uchun)", repo.recent_messages(I1, OWN)[0]["flags"] == ["prepay", "pressure"])

    # spam: bir xil matn
    same = "Bir xil reklama matni, spam sinovi"
    check("birinchi/ikkinchi bir xil matn o'tadi, uchinchisi spam", repo.create_inquiry(L1, ADV2, same)["ok"]
          and repo.create_inquiry(L2, ADV2, same)["ok"] and repo.create_inquiry(L1, ADV3, same)["ok"] is True)
    x = repo.create_inquiry(L2, ADV2, same)
    check("ADV2 yana shu matnni 3-marta yubora olmaydi (spam yoki ochiq so'rov)", not x["ok"] and x["reason"] in ("spam", "open_exists"), str(x))
    I_a = q("SELECT id FROM ad_market_inquiries WHERE advertiser_id = %s AND listing_id = %s", (ADV2, L1))[0][0]
    check("javob xabarida ham bir xil matn spami (add_message)", repo.add_message(I_a, ADV2, same)["reason"] == "spam"
          and repo.add_message(I_a, ADV2, same + " (boshqacha)")["ok"] is True)

    # egasining kunlik kirim limiti
    q("UPDATE ad_market_inquiries SET created_at = NOW() WHERE owner_id = %s", (OWN2,))
    saved = repo.INBOUND_PER_DAY
    repo.INBOUND_PER_DAY = 1
    try:
        busy = repo.create_inquiry(L2, ADV3, "Yangi so'rov, egasi band bo'lishi kerak")
    finally:
        repo.INBOUND_PER_DAY = saved
    check("egasiga kunlik kirim limiti ('busy')", not busy["ok"] and busy["reason"] == "busy", str(busy))

    # o'qilmagan
    def unread_of(uid, iid):
        return next((i["unread"] for i in repo.list_user_inquiries(uid) if i["id"] == iid), None)

    check("egasi uchun o'qilmagan: reklama beruvchining xabarlari", repo.unread_total(OWN) >= 1)
    check("ro'yxatda unread soni (suhbat bo'yicha)", unread_of(OWN, I1) == 1, str(repo.list_user_inquiries(OWN)))
    check("reklama beruvchining o'z xabari unga o'qilmagan emas", all(i["unread"] == 0 for i in repo.list_user_inquiries(ADV)))
    total_before = repo.unread_total(OWN)
    check("mark_read -> shu suhbat o'qilmagani 0, umumiy 1 ga kamaydi", repo.mark_read(I1, OWN) and unread_of(OWN, I1) == 0
          and repo.unread_total(OWN) == total_before - 1)
    repo.add_message(I1, ADV, "Yana bir xabar yozdim")
    check("yangi xabar -> yana o'qilmagan 1", unread_of(OWN, I1) == 1)
    check("begona mark_read ishlamaydi", repo.mark_read(I1, ADV4) is False)
    repo.add_message(I1, OWN, "Javob beraman")
    check("egasi javobi reklama beruvchi uchun o'qilmagan", repo.unread_total(ADV) == 1)

    # foydalanuvchi shikoyati va global ban
    bad = ADV
    reports = []
    for rep_owner in (OWN, OWN2):
        # har bir shikoyat qiluvchida `bad` bilan ochiq suhbat bo'lishi kerak
        pass
    q("DELETE FROM ad_market_inquiries WHERE advertiser_id = %s", (bad,))
    i_own = repo.create_inquiry(L1, bad, "Birinchi egasiga alohida so'rov A")["inquiry_id"]
    i_own2 = repo.create_inquiry(L2, bad, "Ikkinchi egasiga alohida so'rov B")["inquiry_id"]
    r1 = repo.report_user(OWN, i_own)
    r1b = repo.report_user(OWN, i_own)
    check("shikoyat: bir odamdan bitta hisoblanadi", r1["ok"] and r1["count"] == 1 and r1b["reason"] == "again" and r1b["count"] == 1, str(r1b))
    check("begona shikoyat qila olmaydi", repo.report_user(ADV4, i_own)["ok"] is False)
    r2 = repo.report_user(OWN2, i_own2)
    check("2 ta shikoyat — hali ban emas", r2["count"] == 2 and not r2["banned"] and not repo.is_banned(bad))
    # uchinchi shikoyat: boshqa egadan (ADV3 egasi emas -> ADV3 reklama beruvchi sifatida bad bilan suhbatlashgan bo'lishi kerak)
    # ADV3 kanal egasi bo'lib, bad unga yozgan bo'lsin:
    q("INSERT INTO channels (user_id, channel_id, channel_title) VALUES (%s,'-100960000003','Uch')", (ADV3,))
    L3 = repo.create_listing(ADV3, "-100960000003", "safe3", "Uchinchi", "tech", 1000, None)["listing_id"]
    i3 = repo.create_inquiry(L3, bad, "Uchinchi egasiga alohida so'rov C")["inquiry_id"]
    r3 = repo.report_user(ADV3, i3)
    check("3 ta turli shikoyat -> global ban", r3["banned"] and repo.is_banned(bad), str(r3))
    check("ban: e'lonlari bloklanadi, ochiq suhbatlari yopiladi", q("SELECT COUNT(*) FROM ad_market_inquiries WHERE advertiser_id = %s AND status = 'open'", (bad,))[0][0] == 0)
    check("banlangan yangi so'rov yubora olmaydi ('banned')", repo.create_inquiry(L1, bad, "Ban'dan keyin yangi so'rov")["reason"] == "banned")
    q("UPDATE ad_market_inquiries SET status = 'open' WHERE id = %s", (i_own,))
    check("banlangan ochiq suhbatda ham yoza olmaydi (banned)", repo.add_message(i_own, bad, "yana yozaman")["reason"] == "banned")
    q("INSERT INTO channels (user_id, channel_id, channel_title) VALUES (%s,'-100960000009','B')", (bad,))
    check("banlangan e'lon yarata olmaydi", repo.create_listing(bad, "-100960000009", "x", "x", "tech", None, None)["reason"] == "banned")
    check("admin ban'ni olib tashlaydi (shikoyatlar tozalanadi)", repo.admin_set_ban(bad, False) and not repo.is_banned(bad)
          and repo.count_peer_reports(bad) == 0)
    check("admin ban qo'yadi", repo.admin_set_ban(bad, True) and repo.is_banned(bad))
    repo.admin_set_ban(bad, False)
    q("DELETE FROM channels WHERE channel_id IN ('-100960000009','-100960000003')")
    q("DELETE FROM ad_market_listings WHERE channel_id = '-100960000003'")

    # ---------------------------------------------------------- bot oqimi
    print("\n== Bot oqimi: xavfsizlik ==")
    import handlers.ad_market as h  # noqa: E402

    sent = []

    class FakeBot:
        id = 777

        async def send_message(self, chat_id, text, **kw):
            sent.append((chat_id, text, kw))

    def ctx_for(data):
        return SimpleNamespace(bot=FakeBot(), user_data=data, args=[])

    def msg_update(uid, text):
        msg = SimpleNamespace(text=text, from_user=SimpleNamespace(id=uid), reply_text=AsyncMock())
        return SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=uid, full_name="T", username="t"),
                               callback_query=None, effective_chat=SimpleNamespace(send_message=AsyncMock())), msg

    def cb_update(uid, data):
        query = SimpleNamespace(data=data, message=SimpleNamespace(delete=AsyncMock()), answer=AsyncMock(), edit_message_text=AsyncMock())
        return SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=uid, full_name="T", username="t"),
                               effective_chat=SimpleNamespace(send_message=AsyncMock()), message=None), query

    udata = {ADV: {}, ADV4: {}, OWN: {}}
    h.set_market_application(SimpleNamespace(user_data=udata))
    q("DELETE FROM ad_market_inquiries WHERE advertiser_id = ANY(%s)", ([ADV, ADV4],))
    q("DELETE FROM ad_market_messages WHERE sender_id = ANY(%s)", ([ADV, ADV4],))

    def start_inquiry(uid):
        udata[uid][h.INPUT_KEY] = {"kind": "inq", "ts": __import__("time").time(), "listing_id": L1}

    start_inquiry(ADV)
    upd, msg = msg_update(ADV, "Kartamga 8600 1234 5678 9012 ga pul tashlang, shoshiling")
    asyncio.run(h.market_text_input(upd, ctx_for(udata[ADV])))
    check("karta raqamli so'rov yuborilmaydi, sabab tushuntiriladi", "karta raqami" in msg.reply_text.await_args.args[0]
          and q("SELECT COUNT(*) FROM ad_market_inquiries WHERE advertiser_id = %s", (ADV,))[0][0] == 0 and not sent)
    check("rad etilganda kiritish holati saqlanadi (to'g'rilab qayta yozadi)", udata[ADV].get(h.INPUT_KEY))
    upd, msg = msg_update(ADV, "Oldindan to'lov qilaman, shoshiling, kanal haqida gaplashamiz")
    asyncio.run(h.market_text_input(upd, ctx_for(udata[ADV])))
    owner_msg = next((s for s in sent if s[0] == OWN), None)
    check("shubhali so'rov egasiga ⚠️ ogohlantirish va maslahat bilan boradi", owner_msg and "Ehtiyot bo'ling" in owner_msg[1]
          and "oldindan to'lov so'ralmoqda" in owner_msg[1] and "Maslahat" in owner_msg[1], str(owner_msg))
    kb = [b.callback_data for row in owner_msg[2]["reply_markup"].inline_keyboard for b in row]
    check("egasi tugmalarida «🚩 Firibgar» bor", any(c and c.startswith("mk:f:") for c in kb), str(kb))
    IQ = q("SELECT id FROM ad_market_inquiries WHERE advertiser_id = %s", (ADV,))[0][0]
    # yangi hisob belgisi
    q("DELETE FROM ad_market_inquiries WHERE advertiser_id = %s", (ADV4,))
    start_inquiry(ADV4)
    sent.clear()
    upd, msg = msg_update(ADV4, "Salom, kanalingizga reklama bermoqchiman, narxi qancha?")
    asyncio.run(h.market_text_input(upd, ctx_for(udata[ADV4])))
    check("yangi foydalanuvchi so'rovi egasiga «Yangi foydalanuvchi» belgisi bilan boradi", sent and "Yangi foydalanuvchi" in sent[0][1], str(sent))
    # egasi shikoyat qiladi
    sent.clear()
    upd, query = cb_update(OWN, f"mk:f:{IQ}")
    asyncio.run(h.market_callback(upd, ctx_for(udata[OWN])))
    check("🚩 Firibgar: suhbat yopiladi va reklama beruvchi bloklanadi", repo.get_inquiry(IQ, OWN)["status"] == "closed"
          and repo.is_blocked(OWN, ADV) and repo.count_peer_reports(ADV) == 1)
    upd, query = cb_update(OWN, f"mk:f:{IQ}")
    asyncio.run(h.market_callback(upd, ctx_for(udata[OWN])))
    check("takroriy shikoyat 'allaqachon' deb qaytadi", any("allaqachon" in (c.args[0] if c.args else "") for c in query.answer.await_args_list))
    # admin userban
    admin = SimpleNamespace(message=SimpleNamespace(text=f"/market_userban {ADV3}", reply_text=AsyncMock()),
                            effective_user=SimpleNamespace(id=int(os.environ["ADMIN_ID"])))
    asyncio.run(h.market_admin_command(admin, SimpleNamespace(args=[str(ADV3)], bot=FakeBot())))
    check("admin /market_userban foydalanuvchini chetlatadi", repo.is_banned(ADV3))
    asyncio.run(h.market_admin_command(SimpleNamespace(message=SimpleNamespace(text=f"/market_userunban {ADV3}", reply_text=AsyncMock()),
                                                       effective_user=SimpleNamespace(id=int(os.environ["ADMIN_ID"]))),
                                       SimpleNamespace(args=[str(ADV3)], bot=FakeBot())))
    check("admin /market_userunban qaytaradi", not repo.is_banned(ADV3))
    non_admin = SimpleNamespace(message=SimpleNamespace(text=f"/market_userban {ADV2}", reply_text=AsyncMock()), effective_user=SimpleNamespace(id=ADV))
    asyncio.run(h.market_admin_command(non_admin, SimpleNamespace(args=[str(ADV2)], bot=FakeBot())))
    check("oddiy foydalanuvchi admin buyrug'ini bajara olmaydi", not repo.is_banned(ADV2))
    # hisobni o'chirish: ban saqlanadi, e'lon/suhbat o'chadi
    repo.admin_set_ban(ADV2, True)
    with db.db_cursor(commit=True) as cur:
        repo.delete_user_market_data(cur, ADV2)
    check("hisob o'chirilganda ban SAQLANADI (qochib bo'lmasin)", repo.is_banned(ADV2))
finally:
    cleanup()

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip={skipped}")
sys.exit(1 if failed else 0)
