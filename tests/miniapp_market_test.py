#!/usr/bin/env python3
"""Mini App — Reklama birjasi API (real PostgreSQL, soxta Telegram Bot): katalog, e'lon, so'rov, yozishma, himoya.

Faqat SINOV bazasi (URL bo'lmasa SKIP). Test faqat o'z qatorlarini (user_id >= 9_500_000_000) yozadi va o'chiradi.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("MINIAPP_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "INTEGRITY_TEST_DATABASE_URL", server_dir="yordamchi_pg_miniapp_market")
if URL:
    os.environ["DATABASE_URL"] = URL
from miniapp_testkit import FAKE_TOKEN, NOW, Counter, make_init_data  # noqa: E402

T = Counter("MINI APP — REKLAMA BIRJASI API (real PostgreSQL)")
OWN, ADV, ADV2, ADV3, STR = 9_500_000_001, 9_500_000_002, 9_500_000_003, 9_500_000_004, 9_500_000_005
IDS = (OWN, ADV, ADV2, ADV3, STR)
CH_OK, CH_PRIV, CH_NOADM, CH_OTHER = "-100950000001", "-100950000002", "-100950000003", "-100950000004"


def main() -> int:
    if not URL:
        T.skip("birja API testi", "BLOCKED: MINIAPP_TEST_DATABASE_URL (sinov bazasi) berilmagan")
        return T.finish()

    import psycopg2
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    import database as db
    from miniapp_api import app as appmod
    from miniapp_api.db import ReadOnlyRunner
    from miniapp_api.errors import catalog_codes
    from miniapp_api.market import MarketApi
    from miniapp_api.service import MiniAppService
    from miniapp_api.settings import load_settings

    db.init_db()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def run(coro):
        return loop.run_until_complete(coro)

    conn = psycopg2.connect(URL)
    conn.autocommit = True
    cur = conn.cursor()

    def cleanup():
        cur.execute("DELETE FROM ad_market_blocks WHERE owner_id = ANY(%s)", (list(IDS),))
        cur.execute("DELETE FROM ad_market_user_reports WHERE reporter_id = ANY(%s) OR reported_id = ANY(%s)", (list(IDS), list(IDS)))
        cur.execute("DELETE FROM ad_market_bans WHERE user_id = ANY(%s)", (list(IDS),))
        cur.execute("DELETE FROM ad_market_listings WHERE owner_id = ANY(%s)", (list(IDS),))
        cur.execute("DELETE FROM channel_posts_history WHERE channel_id = ANY(%s)", ([CH_OK, CH_PRIV, CH_NOADM, CH_OTHER],))
        cur.execute("DELETE FROM channels WHERE user_id = ANY(%s)", (list(IDS),))
        cur.execute("DELETE FROM users WHERE user_id = ANY(%s)", (list(IDS),))

    sent = []

    class FakeBot:
        id = 777
        chats = {
            CH_OK: SimpleNamespace(id=int(CH_OK), username="mkchan", title="Birja kanal"),
            CH_PRIV: SimpleNamespace(id=int(CH_PRIV), username=None, title="Yopiq"),
            CH_NOADM: SimpleNamespace(id=int(CH_NOADM), username="noadm", title="Admin emas"),
        }

        async def initialize(self):
            return None

        async def shutdown(self):
            return None

        async def get_chat(self, ref):
            return self.chats[str(ref)]

        async def get_chat_member(self, chat_id, user_id):
            if str(chat_id) == CH_NOADM and user_id != 777:
                return SimpleNamespace(status="member")
            return SimpleNamespace(status="administrator")

        async def get_chat_member_count(self, chat_id):
            return 2400

        async def send_message(self, chat_id, text, **kw):
            sent.append((chat_id, text, kw))

    cleanup()
    try:
        for uid in IDS:
            cur.execute("INSERT INTO users (user_id, username, full_name, language_code, plan_type, phone_country, uz_verified) VALUES (%s,%s,%s,'uz','free','UZ',TRUE)",
                        (uid, f"u{uid}", f"Name{uid}"))
        cur.execute("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES (%s,%s,'Birja kanal',TRUE),"
                    "(%s,%s,'Yopiq',TRUE),(%s,%s,'Admin emas',TRUE),(%s,%s,'Boshqa',TRUE)",
                    (OWN, CH_OK, OWN, CH_PRIV, OWN, CH_NOADM, STR, CH_OTHER))
        for i in range(5):
            cur.execute("INSERT INTO channel_posts_history (channel_id, message_id, content, views, post_date) "
                        "VALUES (%s,%s,'x',%s, NOW() - (%s || ' days')::INTERVAL)", (CH_OK, i + 1, 600, str(i)))

        settings = load_settings({"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "test",
                                  "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1", "MINIAPP_REQUIRE_HTTPS": "0"})
        runner = ReadOnlyRunner(statement_timeout_ms=5000, max_inflight=4)
        service = MiniAppService(settings, runner)

        class Null:
            async def hit(self, *a, **k):
                return None

        market = MarketApi(service, settings, bot_factory=FakeBot)
        api = appmod.build_api_app(settings, runner=runner, limiter=Null(), clock=lambda: NOW, service=service, market=market)
        app = web.Application()
        app.add_subapp(appmod.API_PREFIX, api)

        async def make_client():
            c = TestClient(TestServer(app))
            await c.start_server()
            return c

        client = run(make_client())

        async def call(method, path, uid, body=None, auth=True):
            headers = {"Authorization": "tma " + make_init_data(uid)} if auth else {}
            r = await client.request(method, "/api/v1" + path, headers=headers, **({"json": body} if body is not None else {}))
            return r.status, await r.json()

        def C(*a, **k):
            return run(call(*a, **k))

        print("\n== 1. Kirish va tekshiruvlar ==")
        T.check("avtorizatsiyasiz -> 401", C("GET", "/market/summary", OWN, auth=False)[0] == 401)
        T.check("ro'yxatdan o'tmagan -> 403", C("GET", "/market/summary", 9_500_000_099)[0] == 403)
        st, s = C("GET", "/market/summary", OWN)
        T.check("summary: kategoriyalar va limitlar", st == 200 and "tech" in s["categories"] and s["max_listings"] == 5, str(s))
        for code in ("market_private", "market_not_admin", "market_limit", "inquiry_limit", "inquiry_blocked", "inquiry_exists", "thread_closed"):
            T.check(f"xato kodi katalogda: {code}", code in catalog_codes())

        print("\n== 2. E'lon qilish ==")
        good = {"channel_id": CH_OK, "category": "tech", "price": 60000, "description": "Texnologiya yangiliklari"}
        T.check("noma'lum maydon rad etiladi (mass-assignment)", C("POST", "/market/mine", OWN, {**good, "status": "blocked"})[0] == 422)
        T.check("noto'g'ri kategoriya -> 422 (field=category)", (lambda r: r[0] == 422 and r[1]["error"]["field"] == "category")(C("POST", "/market/mine", OWN, {**good, "category": "x"})))
        T.check("narx 500 (juda kam) -> 422", C("POST", "/market/mine", OWN, {**good, "price": 500})[0] == 422)
        T.check("narx bool -> 422", C("POST", "/market/mine", OWN, {**good, "price": True})[0] == 422)
        T.check("uzun tavsif -> 422", C("POST", "/market/mine", OWN, {**good, "description": "a" * 500})[0] == 422)
        T.check("boshqa odam kanali -> 404 channel_not_found", C("POST", "/market/mine", OWN, {**good, "channel_id": CH_OTHER})[1].get("error", {}).get("code") == "channel_not_found")
        T.check("yopiq kanal -> 422 market_private", C("POST", "/market/mine", OWN, {**good, "channel_id": CH_PRIV})[1]["error"]["code"] == "market_private")
        T.check("admin emas -> 403 market_not_admin", C("POST", "/market/mine", OWN, {**good, "channel_id": CH_NOADM})[1]["error"]["code"] == "market_not_admin")
        st, pub = C("POST", "/market/mine", OWN, good)
        lid = pub["listing"]["id"] if st == 201 else None
        T.check("e'lon yaratildi (201), egasiga status/hisoblagichlar ko'rinadi", st == 201 and pub["listing"]["status"] == "active"
                and pub["listing"]["view_count"] == 0 and pub["listing"]["username"] == "mkchan", str(pub))
        T.check("ko'rsatkichlar bazadan: ko'rish 600, ER 25.0%, obunachi 2400",
                pub["listing"]["avg_views"] == 600 and pub["listing"]["er_percent"] == 25.0 and pub["listing"]["members"] == 2400, str(pub["listing"]))
        T.check("qayta e'lon -> 409 inquiry_exists", C("POST", "/market/mine", OWN, good)[0] == 409)
        st, mine = C("GET", "/market/mine", OWN)
        T.check("mine: 3 kanal, bittasida e'lon", st == 200 and len(mine["items"]) == 3 and sum(1 for i in mine["items"] if i["listing"]) == 1, str(mine))

        print("\n== 2b. Hudud (davlat/global): tanlash va kanal tilini tekshirish ==")
        T.check("region-check: auth'siz 401; noto'g'ri hudud 422; begona kanal 404",
                C("GET", f"/market/region-check?channel_id={CH_OK}&region=UZ", OWN, auth=False)[0] == 401
                and C("GET", f"/market/region-check?channel_id={CH_OK}&region=XX", OWN)[0] == 422
                and C("GET", f"/market/region-check?channel_id={CH_OTHER}&region=UZ", OWN)[0] == 404)
        st, rc = C("GET", f"/market/region-check?channel_id={CH_OK}&region=UZ", OWN)
        T.check("til noaniq (qisqa nom) -> ogohlantirish YO'Q (fits=null), valyuta so'm", st == 200 and rc["fits"] is None and rc["currency"] == "UZS", str(rc))
        FakeBot.chats[CH_OK].description = "The best daily news and free tips for you"
        st, rc = C("GET", f"/market/region-check?channel_id={CH_OK}&region=UZ", OWN)
        T.check("kanal tavsifi inglizcha, hudud UZ -> fits=false, tavsiya Global (ZZ)", st == 200 and rc["fits"] is False and rc["language"] == "en" and rc["suggested"] == "ZZ", str(rc))
        st, rc = C("GET", f"/market/region-check?channel_id={CH_OK}&region=ZZ", OWN)
        T.check("Global tanlansa hamma til mos, valyuta dollar", st == 200 and rc["fits"] is True and rc["currency"] == "USD", str(rc))
        FakeBot.chats[CH_OK].description = ""
        st, sm = C("GET", "/market/summary", OWN)
        T.check("summary: davlatlar ro'yxati (UZ boshida) va global belgisi", st == 200 and sm["regions"][0] == "UZ" and "RU" in sm["regions"] and "ZZ" not in sm["regions"] and sm["global_region"] == "ZZ")
        T.check("noto'g'ri hudud bilan e'lon -> 422 (field=region)", (lambda r: r[0] == 422 and r[1]["error"]["field"] == "region")(C("POST", "/market/mine", OWN, {**good, "region": "XX"})))
        T.check("e'lon: hudud davlat bo'lishi kerak (ZZ yoki ISO-2), kichik harf ham yaroqsiz tur emas", C("POST", "/market/mine", OWN, {**good, "region": 5})[0] == 422)
        C("DELETE", f"/market/mine/{lid}", OWN)  # birinchi e'lon o'chiriladi; keyin Global bilan, so'ng qaytadan standart bilan
        st, glob = C("POST", "/market/mine", OWN, {**good, "region": "zz", "price": 20})
        T.check("Global e'lon: country=ZZ, valyuta USD (dollarda narx 20)", st == 201 and glob["listing"]["country"] == "ZZ" and glob["listing"]["currency"] == "USD" and glob["listing"]["price"] == 20, str(glob))
        st, cm0 = C("GET", "/market/listings?country=mine", ADV)
        T.check("UZ ko'ruvchi «o'z mamlakati» filtrida GLOBAL kanalni ham ko'radi", st == 200 and any(i["id"] == glob["listing"]["id"] for i in cm0["items"]), str(cm0)[:200])
        C("DELETE", f"/market/mine/{glob['listing']['id']}", OWN)
        st, pub = C("POST", "/market/mine", OWN, good)
        lid = pub["listing"]["id"]
        T.check("region berilmasa — egasining telefon mamlakati (UZ/UZS)", pub["listing"]["country"] == "UZ" and pub["listing"]["currency"] == "UZS", str(pub))

        print("\n== 3. Katalog va karta ==")
        st, cat = C("GET", "/market/listings?category=tech&sort=m&page=0", ADV)
        T.check("katalog: e'lon bor, ichki maydonlarsiz", st == 200 and any(i["id"] == lid for i in cat["items"])
                and all("channel_id" not in i and "view_count" not in i for i in cat["items"]), str(cat)[:300])
        T.check("katalog: noto'g'ri saralash/kategoriya -> 400", C("GET", "/market/listings?sort=z", ADV)[0] == 400
                and C("GET", "/market/listings?category=zzz", ADV)[0] == 400)
        T.check("katalog: noto'g'ri sahifa -> 400", C("GET", "/market/listings?page=abc", ADV)[0] == 400)
        st, cm = C("GET", "/market/listings?country=mine", ADV)
        T.check("katalog country=mine: UZ ko'ruvchi o'z mamlakati e'lonini ko'radi", st == 200 and any(i["id"] == lid for i in cm["items"]) and cm["filter"] == "mine", str(cm)[:200])
        T.check("katalog: e'londa mamlakat va valyuta (UZ/UZS)", any(i["id"] == lid and i["country"] == "UZ" and i["currency"] == "UZS" for i in cm["items"]))
        cur.execute("UPDATE users SET phone_country='DE', uz_verified=FALSE WHERE user_id=%s", (ADV2,))
        st, cd = C("GET", "/market/listings?country=mine", ADV2)
        T.check("DE ko'ruvchi country=mine: UZ e'loni ko'rinmaydi", st == 200 and not any(i["id"] == lid for i in cd["items"]) and cd["viewer_country"] == "DE", str(cd)[:200])
        st, ca = C("GET", "/market/listings?country=all", ADV2)
        T.check("DE ko'ruvchi country=all (global): UZ e'loni ko'rinadi", st == 200 and any(i["id"] == lid for i in ca["items"]))
        T.check("katalog: noto'g'ri country -> 400", C("GET", "/market/listings?country=zz", ADV)[0] == 400)
        cur.execute("UPDATE users SET phone_country=NULL, uz_verified=FALSE WHERE user_id=%s", (STR,))
        st, nr = C("POST", "/market/mine", STR, {**good, "channel_id": CH_OTHER})
        T.check("telefonsiz e'lon qo'yish -> phone_required", nr.get("error", {}).get("code") == "phone_required", str(nr))
        st, card = C("GET", f"/market/listings/{lid}", ADV)
        T.check("karta: ommaviy ma'lumot, is_owner=False", st == 200 and card["is_owner"] is False and card["listing"]["price"] == 60000, str(card))
        st, card_o = C("GET", f"/market/listings/{lid}", OWN)
        T.check("egasi o'zini ko'rsa is_owner=True", card_o["is_owner"] is True)
        cur.execute("SELECT view_count FROM ad_market_listings WHERE id = %s", (lid,))
        T.check("ko'rishlar: faqat reklama beruvchi hisoblandi (1)", cur.fetchone()[0] == 1)
        T.check("mavjud bo'lmagan e'lon -> 404", C("GET", "/market/listings/99999999", ADV)[0] == 404)

        print("\n== 4. So'rov va yozishma ==")
        T.check("qisqa so'rov -> 422", C("POST", f"/market/listings/{lid}/inquiries", ADV, {"text": "salom"})[0] == 422)
        T.check("o'z kanaliga -> 422 inquiry_own", C("POST", f"/market/listings/{lid}/inquiries", OWN, {"text": "o'zimga so'rov yozaman"})[1]["error"]["code"] == "inquiry_own")
        sent.clear()
        st, inq = C("POST", f"/market/listings/{lid}/inquiries", ADV, {"text": "Salom! 1 ta post reklama kerak, byudjet 100 000"})
        iid = inq.get("inquiry_id")
        T.check("so'rov yaratildi (201) va egasiga bot orqali xabar ketdi", st == 201 and inq["delivered"] is True
                and len(sent) == 1 and sent[0][0] == OWN and "100 000" in sent[0][1]
                and any(b.callback_data == f"mk:r:{iid}" for row in sent[0][2]["reply_markup"].inline_keyboard for b in row), str(sent))
        T.check("ikkinchi ochiq so'rov -> 409", C("POST", f"/market/listings/{lid}/inquiries", ADV, {"text": "yana bir so'rov yozaman"})[0] == 409)
        st, th = C("GET", "/market/threads", ADV)
        T.check("suhbatlar ro'yxati (reklama beruvchi roli)", st == 200 and th["items"][0]["role"] == "advertiser")
        T.check("begona suhbatni ocha olmaydi -> 404", C("GET", f"/market/threads/{iid}", ADV2)[0] == 404)
        T.check("begona javob yoza olmaydi -> 404", C("POST", f"/market/threads/{iid}/messages", ADV2, {"text": "hack"})[0] == 404)
        sent.clear()
        st, rp = C("POST", f"/market/threads/{iid}/messages", OWN, {"text": "Salom, 60 000 so'm, ertaga chiqaramiz"})
        T.check("egasi javob berdi, reklama beruvchiga xabar ketdi", st == 201 and sent and sent[0][0] == ADV and "ertaga" in sent[0][1], str(sent))
        st, th = C("GET", f"/market/threads/{iid}", ADV)
        T.check("suhbat: 2 xabar, mine bayrog'i to'g'ri", st == 200 and [m["mine"] for m in th["messages"]] == [True, False], str(th))
        T.check("HTML escape (foydalanuvchi matni teg bo'lib ketmaydi)",
                (lambda: (C("POST", f"/market/threads/{iid}/messages", ADV, {"text": "<b>x</b>"}), "&lt;b&gt;" in sent[-1][1])[1])())
        T.check("blokni reklama beruvchi qo'llay olmaydi -> 404", C("POST", f"/market/threads/{iid}/block", ADV)[0] == 404)
        st, blk = C("POST", f"/market/threads/{iid}/block", OWN)
        T.check("egasi blokladi", st == 200 and blk["blocked"] is True)
        T.check("blokdan keyin yozishma yopiq -> 409", C("POST", f"/market/threads/{iid}/messages", ADV, {"text": "yana"})[0] == 409)
        T.check("bloklangan yangi so'rov yubora olmaydi -> 403", C("POST", f"/market/listings/{lid}/inquiries", ADV, {"text": "qayta yozishga urinish"})[1]["error"]["code"] == "inquiry_blocked")
        st, inq2 = C("POST", f"/market/listings/{lid}/inquiries", ADV2, {"text": "Boshqa reklama beruvchi so'rovi, savol bor"})
        T.check("boshqa reklama beruvchi yoza oladi", st == 201)
        st, cl = C("POST", f"/market/threads/{inq2['inquiry_id']}/close", ADV2)
        T.check("suhbatni yopish; yopiq suhbatga yozib bo'lmaydi", st == 200 and C("POST", f"/market/threads/{inq2['inquiry_id']}/messages", OWN, {"text": "salom"})[0] == 409)

        print("\n== 4b. Firibgarlikdan himoya (Mini App) ==")
        T.check("karta raqamli so'rov -> 422 message_card (yuborilmaydi)",
                C("POST", f"/market/listings/{lid}/inquiries", ADV3, {"text": "Kartamga 8600 1234 5678 9012 tashlang"})[1]["error"]["code"] == "message_card")
        T.check("kripto hamyon -> 422 message_wallet", C("POST", f"/market/listings/{lid}/inquiries", ADV3,
                {"text": "USDT: TJRabPrwbZy45PuZNJbaDDNDBmbZPsbJy5 ga yuboring"})[1]["error"]["code"] == "message_wallet")
        T.check("birinchi xabarda havola -> 422 message_link", C("POST", f"/market/listings/{lid}/inquiries", ADV3,
                {"text": "Saytimizga qarang: https://bit.ly/abc keyin gaplashamiz"})[1]["error"]["code"] == "message_link")
        sent.clear()
        st, sus = C("POST", f"/market/listings/{lid}/inquiries", ADV3, {"text": "Oldindan to'lov qilaman, shoshiling, reklama kerak"})
        T.check("shubhali so'rov yuboriladi, lekin egasiga ⚠️ ogohlantirish va maslahat bilan boradi", st == 201 and sent
                and "Ehtiyot bo'ling" in sent[0][1] and "Maslahat" in sent[0][1], str(sent))
        iid3 = sus["inquiry_id"]
        st, un = C("GET", "/market/unread", OWN)
        T.check("/market/unread: egasida o'qilmagan bor", st == 200 and un["unread"] >= 1, str(un))
        st, th3 = C("GET", f"/market/threads/{iid3}", OWN)
        T.check("egasi suhbatida xabar flags bilan (prepay, pressure) va peer ma'lumoti", st == 200 and th3["messages"][0]["flags"] == ["prepay", "pressure"]
                and th3["peer"]["reports"] == 0, str(th3))
        T.check("o'z xabari flags'siz ko'rinadi (yuboruvchiga ogohlantirish kerak emas)",
                C("GET", f"/market/threads/{iid3}", ADV3)[1]["messages"][0]["flags"] == [])
        st, tl = C("GET", "/market/threads", OWN)
        T.check("ro'yxatda har suhbat uchun unread soni", st == 200 and all("unread" in i for i in tl["items"]), str(tl))
        T.check("suhbat ochilgach o'qilgan deb belgilanadi (unread 0)", C("GET", f"/market/threads/{iid3}", OWN)[0] == 200
                and next(i["unread"] for i in C("GET", "/market/threads", OWN)[1]["items"] if i["id"] == iid3) == 0)
        T.check("begona foydalanuvchi /report qila olmaydi -> 404", C("POST", f"/market/threads/{iid3}/report", ADV2)[0] == 404)
        st, rp = C("POST", f"/market/threads/{iid3}/report", OWN)
        T.check("🚩 Firibgar: shikoyat qabul, suhbat yopiladi, reklama beruvchi bloklanadi", st == 200 and rp["reported"] is True
                and C("POST", f"/market/listings/{lid}/inquiries", ADV3, {"text": "Qayta yozishga urinish, blokdan keyin"})[1]["error"]["code"] == "inquiry_blocked")
        T.check("takroriy shikoyat 'again'", C("POST", f"/market/threads/{iid3}/report", OWN)[1]["again"] is True)
        for code in ("message_card", "message_wallet", "message_link", "message_spam", "user_banned", "owner_busy"):
            T.check(f"xato kodi katalogda: {code}", code in catalog_codes())

        print("\n== 5. Shikoyat va egasi boshqaruvi ==")
        T.check("o'z e'loniga shikoyat -> 422", C("POST", f"/market/listings/{lid}/report", OWN)[0] == 422)
        C("POST", f"/market/listings/{lid}/report", ADV)
        st, again = C("POST", f"/market/listings/{lid}/report", ADV)
        T.check("takroriy shikoyat hisoblanmaydi", again["again"] is True and again["blocked"] is False)
        C("POST", f"/market/listings/{lid}/report", ADV2)
        sent.clear()
        st, last = C("POST", f"/market/listings/{lid}/report", ADV3)
        T.check("3-shikoyat -> e'lon bloklandi", last["blocked"] is True)
        T.check("bloklangan e'lon katalogda yo'q va kartada 404", C("GET", f"/market/listings/{lid}", ADV)[0] == 404)
        T.check("egasi o'zi faollashtira olmaydi -> 403 market_blocked", C("PATCH", f"/market/mine/{lid}", OWN, {"status": "active"})[1]["error"]["code"] == "market_blocked")
        cur.execute("UPDATE ad_market_listings SET status = 'active' WHERE id = %s", (lid,))
        st, up = C("PATCH", f"/market/mine/{lid}", OWN, {"price": None, "category": "news", "description": "Yangi tavsif"})
        T.check("tahrirlash: narx kelishiladi (null), mavzu, tavsif", st == 200 and up["listing"]["price"] is None
                and up["listing"]["category"] == "news" and up["listing"]["description"] == "Yangi tavsif", str(up))
        T.check("begona e'lonni tahrirlay olmaydi -> 404", C("PATCH", f"/market/mine/{lid}", ADV, {"price": 5000})[0] == 404)
        T.check("bo'sh PATCH -> 422; noto'g'ri status -> 422", C("PATCH", f"/market/mine/{lid}", OWN, {})[0] == 422
                and C("PATCH", f"/market/mine/{lid}", OWN, {"status": "blocked"})[0] == 422)
        st, pa = C("PATCH", f"/market/mine/{lid}", OWN, {"status": "paused"})
        T.check("to'xtatildi -> katalogda ko'rinmaydi", st == 200 and pa["listing"]["status"] == "paused" and C("GET", f"/market/listings/{lid}", ADV)[0] == 404)
        st, rf = C("POST", f"/market/mine/{lid}/refresh", OWN)
        T.check("yangilash: ko'rsatkichlar qayta hisoblandi", st == 200 and rf["listing"]["avg_views"] == 600)
        T.check("begona yangilay olmaydi -> 404", C("POST", f"/market/mine/{lid}/refresh", ADV)[0] == 404)
        st, dl = C("DELETE", f"/market/mine/{lid}", OWN)
        T.check("e'lon o'chirildi; suhbatlari ham ketdi", st == 200 and C("GET", f"/market/threads/{iid}", ADV)[0] == 404)
        T.check("qayta o'chirish -> 404", C("DELETE", f"/market/mine/{lid}", OWN)[0] == 404)
        run(client.close())
        run(market.aclose())
    finally:
        cleanup()
        conn.close()
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
