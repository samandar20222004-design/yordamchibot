#!/usr/bin/env python3
"""💰 Reklama birjasi: narx/ko'rsatkich hisobi, uz/ru/en pariteti, real PostgreSQL biznes-qoidalari va bot oqimi.

Real-DB qismi (URL bo'lmasa SKIP): egalik/IDOR, katalog filtri (faol kanal + faol e'lon), saralash, so'rov limiti (kuniga 5,
parallel), bitta ochiq so'rov, blok, o'z kanaliga yozmaslik, yozishma ishtirokchilar bilan cheklangan, xabar limiti,
3 shikoyat -> avto blok, hisob o'chirilsa hammasi ketadi. Bot oqimi: soxta Update/Bot bilan so'rov -> egasiga xabar -> javob.
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
                  "MINIAPP_TEST_DATABASE_URL", server_dir="yordamchi_pg_market")
if URL:
    os.environ["DATABASE_URL"] = URL
os.environ.setdefault("BOT_TOKEN", "123456:AD_MARKET_TEST_TOKEN")
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


# ------------------------------------------------------------------ 1. sof mantiq
from services import ad_market as svc  # noqa: E402
from translations import ad_market_parity_report, market_t  # noqa: E402
from translations.ad_market import AD_MARKET_I18N  # noqa: E402

print("== Reklama birjasi: sof mantiq ==")
for text, expect in (("50000", ("ok", 50000)), ("50 000", ("ok", 50000)), ("50k", ("ok", 50000)), ("50 ming", ("ok", 50000)),
                     ("1.5 mln", ("ok", 1_500_000)), ("1,5 млн", ("ok", 1_500_000)), ("kelishiladi", ("negotiable", None)),
                     ("0", ("negotiable", None)), ("Договорная", ("negotiable", None)), ("abc", ("error", None)),
                     ("500", ("error", None)), ("99999999999", ("error", None)), ("", ("error", None))):
    check(f"narx {text!r} -> {expect}", svc.parse_price(text) == expect, str(svc.parse_price(text)))
check("format_count: 950 / 12 400 / 1.25M / None",
      (svc.format_count(950), svc.format_count(12400), svc.format_count(1250000), svc.format_count(None)) == ("950", "12.4k", "1.25M", "—"),
      str((svc.format_count(950), svc.format_count(12400), svc.format_count(1250000))))

hist = [{"date": "2026-10-17", "member_count": 1200, "source": "x", "collected_at": None},
        {"date": "2026-09-17", "member_count": 1000, "source": "x", "collected_at": None}]
st = svc.compute_stats(live_members=1200, history=hist, views=[300, 300, 300], posts_30d=10)
check("ko'rsatkich: o'rtacha ko'rish 300, ER 25.0%", st["avg_views"] == 300 and st["er_percent"] == 25.0, str(st))
st2 = svc.compute_stats(live_members=1200, history=[], views=[300, 300], posts_30d=0)
check("ko'rish < 3 ta post -> avg_views/ER None (soxta 0 emas)", st2["avg_views"] is None and st2["er_percent"] is None, str(st2))
st3 = svc.compute_stats(live_members=None, history=hist, views=[], posts_30d=0)
check("jonli son yo'q -> snapshot'dagi oxirgi qiymat", st3["members"] == 1200, str(st3))
check("nishonlar faqat faktlardan", svc.listing_badges({"members": 1000, "growth_30d": 50, "er_percent": 31, "posts_30d": 20}) == ["growing", "engaged", "active"]
      and svc.listing_badges({"members": 1000, "growth_30d": None, "er_percent": None, "posts_30d": 1}) == [])

rep = ad_market_parity_report()
check("uz/ru/en pariteti 100%", rep["in_sync"], str({k: v for k, v in rep.items() if k != "keys"}))
long_btn = [(lang, k) for lang, t in AD_MARKET_I18N.items() for k, v in t.items() if k.startswith("mk_btn_") and len(v) > 18]
check("barcha mk_btn_* yorlig'i <= 18 belgi", not long_btn, str(long_btn))
check("matn argumentsiz chaqirilganda ham yiqilmaydi", all(market_t(k, lang) for k in AD_MARKET_I18N["uz"] for lang in ("uz", "ru", "en")))

# ------------------------------------------------------------------ 2. real PostgreSQL
print("\n== Reklama birjasi: real PostgreSQL ==")
if not URL:
    skipped += 1
    print("  [SKIP] real PostgreSQL URL yo'q")
    print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip={skipped}")
    sys.exit(1 if failed else 0)

import database as db  # noqa: E402
from repositories import ad_market_repository as repo  # noqa: E402

db.DATABASE_URL = URL
db._reset_pool()
db.init_db()

OWN, OWN2, ADV, ADV2, ADV3, STR = 9_800_001, 9_800_002, 9_800_003, 9_800_004, 9_800_005, 9_800_006
USERS = (OWN, OWN2, ADV, ADV2, ADV3, STR)
CH1, CH2, CH3 = "-100980000001", "-100980000002", "-100980000003"


def q(sql, params=()):
    with db.db_cursor(commit=True) as cur:
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except Exception:  # noqa: BLE001
            return []


def cleanup():
    q("DELETE FROM ad_market_listings WHERE owner_id = ANY(%s)", (list(USERS),))
    q("DELETE FROM ad_market_blocks WHERE owner_id = ANY(%s) OR blocked_id = ANY(%s)", (list(USERS), list(USERS)))
    q("DELETE FROM ad_market_reports WHERE reporter_id = ANY(%s)", (list(USERS),))
    q("DELETE FROM channel_posts_history WHERE channel_id = ANY(%s)", ([CH1, CH2, CH3],))
    q("DELETE FROM channel_member_counts WHERE channel_id = ANY(%s)", ([CH1, CH2, CH3],))
    q("DELETE FROM channels WHERE channel_id = ANY(%s)", ([CH1, CH2, CH3],))
    q("DELETE FROM users WHERE user_id = ANY(%s)", (list(USERS),))


cleanup()
try:
    for uid in USERS:
        q("INSERT INTO users (user_id, username, plan_type) VALUES (%s, %s, 'free')", (uid, f"m{uid}"))
    q("INSERT INTO channels (user_id, channel_id, channel_title) VALUES (%s, %s, 'Birinchi'), (%s, %s, 'Ikkinchi'), (%s, %s, 'Uchinchi')",
      (OWN, CH1, OWN, CH2, OWN2, CH3))
    for i in range(5):
        q("INSERT INTO channel_posts_history (channel_id, message_id, content, views, post_date) VALUES (%s, %s, 'x', %s, NOW() - (%s || ' days')::INTERVAL)",
          (CH1, i + 1, 400, str(i)))
    db.save_channel_member_count(CH1, 2000)

    check("egalik: o'z kanali topiladi, boshqaning kanali -> None (IDOR)",
          repo.get_owned_channel(OWN, CH1) is not None and repo.get_owned_channel(OWN, CH3) is None and repo.get_owned_channel(ADV, CH1) is None)

    r = repo.create_listing(OWN2, CH1, "birinchi", "Birinchi", "tech", 50000, "tavsif")
    check("boshqa odam kanalini e'lon qila olmaydi (not_owner)", not r["ok"] and r["reason"] == "not_owner", str(r))
    r = repo.create_listing(OWN, CH1, "birinchi", "Birinchi", "tech", 50000, "Texnologiya yangiliklari")
    check("e'lon yaratildi", r["ok"] and r["listing_id"], str(r))
    L1 = r["listing_id"]
    r2 = repo.create_listing(OWN, CH1, "birinchi", "Birinchi", "tech", 1, None)
    check("bir kanal ikki marta e'lon qilinmaydi (exists)", not r2["ok"] and r2["reason"] == "exists" and r2["listing_id"] == L1, str(r2))
    L2 = repo.create_listing(OWN, CH2, "ikkinchi", "Ikkinchi", "news", None, None)["listing_id"]
    L3 = repo.create_listing(OWN2, CH3, "uchinchi", "Uchinchi", "tech", 20000, None)["listing_id"]

    stats = __import__("services.ad_market", fromlist=["x"]).refresh_listing_stats(L1, CH1, 2000)
    check("ko'rsatkich bazadagi postlardan: ko'rish 400, ER 20.0%", stats["avg_views"] == 400 and stats["er_percent"] == 20.0 and stats["posts_30d"] == 5, str(stats))
    L1d = repo.get_listing(L1)
    check("ko'rsatkichlar saqlandi", L1d["members"] == 2000 and L1d["avg_views"] == 400 and L1d["er_percent"] == 20.0 and L1d["stats_updated_at"], str(L1d))

    cat = repo.list_catalog("all", "m")
    ids = [i["id"] for i in cat["items"]]
    check("katalog: 3 ta e'lon, obunachi bo'yicha (L1 birinchi)", cat["total"] >= 3 and ids[0] == L1 and {L1, L2, L3} <= set(ids), str(ids))
    check("katalog mavzu filtri", {i["id"] for i in repo.list_catalog("news")["items"]} >= {L2} and L1 not in {i["id"] for i in repo.list_catalog("news")["items"]})
    check("narx bo'yicha saralash: arzoni oldin, kelishiladigan oxirida",
          [i["id"] for i in repo.list_catalog("all", "p")["items"] if i["id"] in (L1, L2, L3)] == [L3, L1, L2])

    # holat/faol kanal
    check("egasi to'xtatdi -> katalogda yo'q", repo.set_listing_status(L2, OWN, "paused") and L2 not in {i["id"] for i in repo.list_catalog("all")["items"]})
    check("boshqa odam holatni o'zgartira olmaydi", not repo.set_listing_status(L2, ADV, "active") and repo.get_listing(L2)["status"] == "paused")
    q("UPDATE channels SET is_active = FALSE WHERE channel_id = %s", (CH3,))
    check("kanal faolsizlansa e'lon katalogdan yo'qoladi va so'rov qabul qilmaydi",
          L3 not in {i["id"] for i in repo.list_catalog("all")["items"]} and repo.get_public_listing(L3) is None
          and repo.create_inquiry(L3, ADV, "salom reklama")["reason"] == "not_found")
    q("UPDATE channels SET is_active = TRUE WHERE channel_id = %s", (CH3,))

    v0 = repo.get_listing(L1)["view_count"]
    repo.get_public_listing(L1, ADV)
    repo.get_public_listing(L1, OWN)
    check("ko'rishlar: reklama beruvchi +1, egasi o'zini ko'rsa hisoblanmaydi", repo.get_listing(L1)["view_count"] == v0 + 1)
    check("faqat ruxsat etilgan maydonlar tahrirlanadi",
          repo.update_listing_fields(L1, OWN, price_post=60000, channel_id="hack", status="blocked") and repo.get_listing(L1)["price_post"] == 60000
          and repo.get_listing(L1)["owner_id"] == OWN and repo.get_listing(L1)["status"] == "active")
    check("boshqa odam e'lonni tahrirlay olmaydi", not repo.update_listing_fields(L1, ADV, price_post=1))

    # so'rovlar
    r = repo.create_inquiry(L1, OWN, "o'z kanalim")
    check("o'z kanaliga so'rov yozib bo'lmaydi (own)", not r["ok"] and r["reason"] == "own")
    r = repo.create_inquiry(L1, ADV, "Salom, reklama bermoqchiman")
    check("so'rov yaratildi (owner_id to'g'ri)", r["ok"] and r["owner_id"] == OWN, str(r))
    I1 = r["inquiry_id"]
    r = repo.create_inquiry(L1, ADV, "yana")
    check("bitta ochiq so'rov (open_exists)", not r["ok"] and r["reason"] == "open_exists" and r["inquiry_id"] == I1, str(r))
    check("e'lon hisoblagichi +1", repo.get_listing(L1)["inquiry_count"] == 1)

    # parallel: kuniga 5 limit
    import threading
    q("DELETE FROM ad_market_inquiries WHERE advertiser_id = %s", (ADV2,))
    q("INSERT INTO channels (user_id, channel_id, channel_title) SELECT %s, '-10098100000' || g, 'E' || g FROM generate_series(1, 4) g", (OWN2,))
    lids = []
    for g in range(1, 5):
        lids.append(repo.create_listing(OWN2, f"-10098100000{g}", f"extra{g}", f"E{g}", "other", None, None)["listing_id"])
    lids.append(L1)
    results = []

    def go(lid):
        results.append(repo.create_inquiry(lid, ADV2, "reklama haqida savol bor"))

    # 6 ta turli e'longa parallel urinish (L1 da ochiq so'rov ADV2 da yo'q; L3 egasi OWN2)
    threads = [threading.Thread(target=go, args=(lid,)) for lid in lids + [L3]]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    okc = sum(1 for x in results if x["ok"])
    check("kuniga 5 tadan ko'p yangi so'rov o'tmaydi (parallel ham)", okc <= repo.INQUIRIES_PER_DAY, f"ok={okc} {[x['reason'] for x in results]}")
    check("aynan 5 tasi o'tdi, qolgani 'limit'", okc == repo.INQUIRIES_PER_DAY and sum(1 for x in results if x["reason"] == "limit") == len(results) - okc,
          str([x["reason"] for x in results]))

    # yozishma
    check("begona odam so'rovni o'qiy olmaydi", repo.get_inquiry(I1, ADV3) is None and repo.recent_messages(I1, ADV3) == [])
    check("begona odam xabar yoza olmaydi", not repo.add_message(I1, ADV3, "hack")["ok"])
    m = repo.add_message(I1, OWN, "Salom, 60 000 so'm")
    check("egasi javob yozdi, qabul qiluvchi — reklama beruvchi", m["ok"] and m["recipient_id"] == ADV, str(m))
    inq = repo.get_inquiry(I1, OWN)
    check("rollar: egasi=owner, peer=ADV", inq["role"] == "owner" and inq["peer_id"] == ADV and repo.get_inquiry(I1, ADV)["role"] == "advertiser")
    check("xabarlar eskidan yangiga", [x["body"] for x in repo.recent_messages(I1, ADV)] == ["Salom, reklama bermoqchiman", "Salom, 60 000 so'm"])
    q("UPDATE ad_market_inquiries SET msg_count = %s WHERE id = %s", (repo.MAX_MESSAGES_PER_INQUIRY, I1))
    full = repo.add_message(I1, ADV, "yana")
    check("xabar limiti tugasa 'full'", not full["ok"] and full["reason"] == "full", str(full))
    q("UPDATE ad_market_inquiries SET msg_count = 3 WHERE id = %s", (I1,))

    # blok
    check("egasi bloklaydi; reklama beruvchi bloklay olmaydi",
          repo.block_advertiser(ADV, I1) is None and repo.block_advertiser(OWN, I1) is not None)
    check("bloklangan ochiq so'rovlar yopildi va yangisi rad etiladi",
          repo.get_inquiry(I1, ADV)["status"] == "closed" and repo.create_inquiry(L1, ADV, "qayta yozaman")["reason"] == "blocked")
    check("yopiq suhbatga yozib bo'lmaydi", repo.add_message(I1, ADV, "x")["reason"] == "closed")

    # shikoyat
    check("o'z e'loniga shikoyat qilib bo'lmaydi", repo.report_listing(L1, OWN)["reason"] == "own")
    a = repo.report_listing(L1, ADV)
    b = repo.report_listing(L1, ADV)
    check("bir foydalanuvchi bitta e'longa bir marta shikoyat qiladi", a["ok"] and b["reason"] == "again" and b["count"] == 1, str(b))
    repo.report_listing(L1, ADV2)
    c = repo.report_listing(L1, ADV3)
    check("3 ta turli shikoyat -> avtomatik blok", c["blocked"] and repo.get_listing(L1)["status"] == "blocked", str(c))
    check("bloklangan e'lon katalogda yo'q, egasi o'zi faollashtira olmaydi",
          L1 not in {i["id"] for i in repo.list_catalog("all")["items"]} and not repo.set_listing_status(L1, OWN, "active"))
    check("admin qayta faollashtiradi (shikoyatlar tozalanadi)", repo.admin_set_listing_status(L1, "active") and repo.get_listing(L1)["status"] == "active"
          and q("SELECT COUNT(*) FROM ad_market_reports WHERE listing_id = %s", (L1,))[0][0] == 0)

    # ------------------------------------------------------------ bot oqimi (soxta Telegram)
    print("\n== Reklama birjasi: bot oqimi ==")
    import handlers.ad_market as h  # noqa: E402

    sent = []

    class FakeBot:
        id = 777

        async def send_message(self, chat_id, text, **kw):
            sent.append((chat_id, text, kw))

        async def get_chat(self, ref):
            return SimpleNamespace(id=-100980000002, username="ikkinchi", title="Ikkinchi")

        async def get_chat_member(self, chat_id, user_id):
            return SimpleNamespace(status="administrator")

        async def get_chat_member_count(self, chat_id):
            return 1500

    def make_ctx(app_data):
        return SimpleNamespace(bot=FakeBot(), user_data=app_data, args=[])

    def make_cb_update(uid, data):
        query = SimpleNamespace(data=data, message=SimpleNamespace(delete=AsyncMock()), answer=AsyncMock(), edit_message_text=AsyncMock())
        chat = SimpleNamespace(send_message=AsyncMock())
        return SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=uid, full_name="Test User", username="tuser"),
                               effective_chat=chat, message=None), query, chat

    def make_msg_update(uid, text):
        msg = SimpleNamespace(text=text, from_user=SimpleNamespace(id=uid), reply_text=AsyncMock())
        return SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=uid, full_name="Test User", username="tuser"),
                               callback_query=None, effective_chat=SimpleNamespace(send_message=AsyncMock())), msg

    users_data = {ADV3: {}, OWN: {}}
    h.set_market_application(SimpleNamespace(user_data=users_data))
    q("DELETE FROM ad_market_blocks WHERE owner_id = %s", (OWN,))
    q("DELETE FROM ad_market_inquiries WHERE advertiser_id = %s", (ADV3,))

    # bosh ekran, katalog, karta
    upd, query, _ = make_cb_update(ADV3, "mk:home")
    asyncio.run(h.market_callback(upd, make_ctx(users_data[ADV3])))
    check("mk:home -> bosh ekran chiziladi", query.edit_message_text.await_count == 1 and "Reklama birjasi" in query.edit_message_text.await_args.args[0])
    upd, query, _ = make_cb_update(ADV3, "mk:l:all:m:0")
    asyncio.run(h.market_callback(upd, make_ctx(users_data[ADV3])))
    kb = query.edit_message_text.await_args.kwargs["reply_markup"].inline_keyboard
    datas = [b.callback_data for row in kb for b in row]
    check("katalog: e'lon tugmasi mk:v:<id> bor", f"mk:v:{L1}" in datas, str(datas))
    check("katalog: barcha callback_data <= 64 bayt", all(len((d or "").encode()) <= 64 for d in datas))
    upd, query, _ = make_cb_update(ADV3, f"mk:v:{L1}")
    asyncio.run(h.market_callback(upd, make_ctx(users_data[ADV3])))
    card = query.edit_message_text.await_args.args[0]
    check("karta: obunachi, ko'rish, ER, narx va tekshirilgan belgisi", "2 000" in card and "400" in card and "20.0%" in card and "60 000" in card and "tekshirilgan" in card, card)
    kb = query.edit_message_text.await_args.kwargs["reply_markup"].inline_keyboard
    check("karta: kanalni ochish havolasi t.me/<username>", any(getattr(b, "url", None) == "https://t.me/birinchi" for row in kb for b in row))

    # so'rov yozish
    ctx_adv = make_ctx(users_data[ADV3])
    upd, query, chat = make_cb_update(ADV3, f"mk:q:{L1}")
    asyncio.run(h.market_callback(upd, ctx_adv))
    check("so'rov boshlandi: kiritish holati o'rnatildi", users_data[ADV3].get(h.INPUT_KEY, {}).get("kind") == "inq")
    check("filtr: faol holatdagi oddiy matnga mos, buyruqqa mos emas",
          h.MarketInputFilter.filter(SimpleNamespace(text="salom", from_user=SimpleNamespace(id=ADV3)))
          and not h.MarketInputFilter.filter(SimpleNamespace(text="/start", from_user=SimpleNamespace(id=ADV3)))
          and not h.MarketInputFilter.filter(SimpleNamespace(text="salom", from_user=SimpleNamespace(id=ADV))))
    upd, msg = make_msg_update(ADV3, "qisqa")
    asyncio.run(h.market_text_input(upd, ctx_adv))
    check("juda qisqa so'rov rad etiladi, holat saqlanadi", msg.reply_text.await_count == 1 and users_data[ADV3].get(h.INPUT_KEY))
    sent.clear()
    upd, msg = make_msg_update(ADV3, "Salom! Yangi kafe ochildi, 1 ta post reklama kerak, byudjet 100 000 so'm")
    asyncio.run(h.market_text_input(upd, ctx_adv))
    check("so'rov yuborildi: egasiga xabar ketdi (javob tugmali)", len(sent) == 1 and sent[0][0] == OWN and "Yangi reklama so'rovi" in sent[0][1]
          and any(b.callback_data.startswith("mk:r:") for row in sent[0][2]["reply_markup"].inline_keyboard for b in row), str(sent))
    check("holat tozalandi", h.INPUT_KEY not in users_data[ADV3])
    inq_row = q("SELECT id FROM ad_market_inquiries WHERE advertiser_id = %s AND status = 'open'", (ADV3,))
    IQ = inq_row[0][0]

    # egasi javob beradi
    ctx_own = make_ctx(users_data[OWN])
    upd, query, chat = make_cb_update(OWN, f"mk:r:{IQ}")
    asyncio.run(h.market_callback(upd, ctx_own))
    sent.clear()
    upd, msg = make_msg_update(OWN, "Salom! 60 000 so'm, ertaga chiqaramiz")
    asyncio.run(h.market_text_input(upd, ctx_own))
    check("egasi javobi reklama beruvchiga yetkazildi", len(sent) == 1 and sent[0][0] == ADV3 and "ertaga chiqaramiz" in sent[0][1], str(sent))

    # kontakt ulashish va suhbat yopish
    sent.clear()
    upd, query, _ = make_cb_update(ADV3, f"mk:c:{IQ}")
    asyncio.run(h.market_callback(upd, ctx_adv))
    check("kontakt FAQAT bosilganda ulashiladi (tg://user?id=...)", len(sent) == 1 and sent[0][0] == OWN and f"tg://user?id={ADV3}" in sent[0][1], str(sent))
    upd, query, _ = make_cb_update(ADV, f"mk:t:{IQ}")
    asyncio.run(h.market_callback(upd, make_ctx({})))
    check("begona odam suhbatni ocha olmaydi", query.edit_message_text.await_count == 0)
    sent.clear()
    upd, query, _ = make_cb_update(ADV3, f"mk:x:{IQ}")
    asyncio.run(h.market_callback(upd, ctx_adv))
    check("suhbat yopildi, ikkinchi tomon xabar oldi", repo.get_inquiry(IQ, ADV3)["status"] == "closed" and any(s[0] == OWN for s in sent))

    # shikoyat bosilganda admin xabari (3-shikoyat)
    sent.clear()
    q("DELETE FROM ad_market_reports WHERE listing_id = %s", (L2,))
    repo.set_listing_status(L2, OWN, "active")
    for rep_id in (ADV, ADV2):
        repo.report_listing(L2, rep_id)
    upd, query, _ = make_cb_update(ADV3, f"mk:rp:{L2}")
    asyncio.run(h.market_callback(upd, ctx_adv))
    check("3-shikoyatda e'lon bloklandi va adminga xabar ketdi", repo.get_listing(L2)["status"] == "blocked" and any("avtomatik bloklandi" in s[1] for s in sent), str(sent))

    # kanal egasi: yangi e'lon oqimi (CH2 e'loni o'chirilib qayta yaratiladi)
    repo.delete_listing(L2, OWN)
    users_data[OWN].clear()
    upd, query, chat = make_cb_update(OWN, f"mk:lc:{CH2}")
    asyncio.run(h.market_callback(upd, ctx_own))
    check("kanal egasi: mavzu tanlash ekrani", "1/3" in query.edit_message_text.await_args.args[0])
    upd, query, chat = make_cb_update(OWN, "mk:nc:shop")
    asyncio.run(h.market_callback(upd, ctx_own))
    upd, msg = make_msg_update(OWN, "xato narx")
    asyncio.run(h.market_text_input(upd, ctx_own))
    check("noto'g'ri narx rad etiladi", msg.reply_text.await_count == 1 and users_data[OWN][h.INPUT_KEY]["kind"] == "price_new")
    upd, msg = make_msg_update(OWN, "75k")
    asyncio.run(h.market_text_input(upd, ctx_own))
    upd, msg = make_msg_update(OWN, "Savdo kanali <b>test</b>")
    asyncio.run(h.market_text_input(upd, ctx_own))
    new_l = q("SELECT id, price_post, category, description FROM ad_market_listings WHERE channel_id = %s", (CH2,))
    check("e'lon narx 75 000, mavzu shop, tavsif bilan yaratildi", new_l and new_l[0][1] == 75000 and new_l[0][2] == "shop" and "test" in new_l[0][3], str(new_l))
    check("e'lon xabarida HTML escape qilingan (tavsifdagi <b> teg emas)", "&lt;b&gt;" in msg.reply_text.await_args.args[0], msg.reply_text.await_args.args[0][:300])

    # hisob o'chirilganda
    r = repo.create_inquiry(new_l[0][0], ADV3, "o'chirish sinovi uchun so'rov")
    with db.db_cursor(commit=True) as cur:
        out = repo.delete_user_market_data(cur, OWN)
    check("hisob o'chirilsa egasining e'lonlari, so'rovlari, xabarlari ketadi",
          out["ad_market_listings"] >= 1 and q("SELECT COUNT(*) FROM ad_market_listings WHERE owner_id = %s", (OWN,))[0][0] == 0
          and q("SELECT COUNT(*) FROM ad_market_messages WHERE inquiry_id = %s", (r["inquiry_id"],))[0][0] == 0, str(out))
    # kanal paneli tugmasi
    from keyboards.inline import get_channel_contextual_keyboard
    kb = get_channel_contextual_keyboard(CH1, "uz").inline_keyboard
    check("kanal panelida «Reklama birjasi» tugmasi (mk:lc:<kanal>)", any(b.callback_data == f"mk:lc:{CH1}" for row in kb for b in row))
finally:
    q("DELETE FROM channels WHERE channel_id LIKE '-10098100000%%'")
    cleanup()

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip={skipped}")
sys.exit(1 if failed else 0)
