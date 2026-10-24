#!/usr/bin/env python3
"""🔗 Manba havolalari: ``?start=s_<kod>`` — kim qaysi havola bilan kelgani, ball kimga yozilishi va admin hisobotlari.

DB'siz qism: kod/parametr tekshiruvi, buyruq argumentlari, matnlar (3 til, HTML-escape, tugma ≤18), /start oqimi
(soxta ``run_db``: egasi taklif qiluvchi bo'ladi, o'chirilgan/yaroqsiz havola e'tiborsiz, ``ref_`` buzilmaydi).
Real PostgreSQL qismi (``MINIAPP_TEST_DATABASE_URL`` va h.k. — FAQAT sinov bazasi; URL bo'lmasa SKIP): havolalar ``zt_``
prefiksi bilan yoziladi va o'chiriladi.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "telegram_bot"))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("MINIAPP_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "INTEGRITY_TEST_DATABASE_URL", server_dir="yordamchi_pg_tracked_links")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("BOT_TOKEN", "123456:TRACKED_LINKS_TEST")
os.environ["DATABASE_URL"] = URL or "postgresql://test:test@127.0.0.1:5432/test"
from miniapp_testkit import Counter  # noqa: E402

T = Counter("MANBA HAVOLALARI (s_<kod>)")
OWNER, NEW1, NEW2, OLD, ADM = 9_710_000_001, 9_710_000_002, 9_710_000_003, 9_710_000_004, 9_710_000_005
IDS = (OWNER, NEW1, NEW2, OLD, ADM)


# ---------------------------------------------------------------- A. DB'siz

def offline() -> None:
    print("\n== A. Kod, argumentlar va matnlar (DB'siz) ==")
    from handlers import tracked_links as H
    from repositories import tracked_links_repository as TL
    from translations.tracked_links import TRACKED_LINKS_I18N, links_t, tracked_links_parity_report

    T.check("uz/ru/en pariteti", tracked_links_parity_report()["in_sync"], str(tracked_links_parity_report())[:300])
    for lang in ("uz", "ru", "en"):
        for key, val in TRACKED_LINKS_I18N[lang].items():
            if key.startswith("tl_btn_"):
                T.check(f"[{lang}] {key} ≤18 belgi", len(val) <= 18, val)
    T.check("kod: kichik harf, probel/tire -> _", TL.normalize_code(" Tech-Kanal 1 ") == "tech_kanal_1")
    T.check("kod: yaroqsiz belgi / qisqa / uzun -> None",
            TL.normalize_code("a") is None and TL.normalize_code("kod!") is None and TL.normalize_code("x" * 25) is None
            and TL.normalize_code("kirill_код") is None)
    T.check("payload: s_<kod> o'qiladi", TL.code_from_payload("s_tech_1") == "tech_1")
    T.check("payload: boshqa parametrlar e'tiborsiz",
            TL.code_from_payload("ref_5") is None and TL.code_from_payload("team_abcdefgh") is None
            and TL.code_from_payload("s_") is None and TL.code_from_payload("s_BAD!") is None and TL.code_from_payload(None) is None)
    T.check("havola matni ≤64 belgi (Telegram chegarasi)", len(TL.payload_for("x" * 24)) <= 64)
    T.check("havola URL", H.link_url("PostAssistBot", "tech") == "https://t.me/PostAssistBot?start=s_tech")
    T.check("argument: kod + nom", H.parse_new_args(["tech", "Texno", "kanal"]) == ("tech", None, "Texno kanal"))
    T.check("argument: kod + @egasi + nom", H.parse_new_args(["ali", "@ali_smm", "Ali", "hamkor"]) == ("ali", "@ali_smm", "Ali hamkor"))
    T.check("argument: kod + ID egasi", H.parse_new_args(["b", "12345", "Nom"]) == ("b", "12345", "Nom"))
    T.check("argument: bo'sh", H.parse_new_args([]) == (None, None, ""))

    items = [
        {"id": 1, "code": "tech", "title": "Texno <b>kanal</b>", "owner_id": None, "is_active": True, "clicks": 40,
         "visitors": 30, "new_users": 20, "with_channel": 12, "posted": 8, "paid": 2, "created_at": None},
        {"id": 2, "code": "ali", "title": "Ali", "owner_id": 777, "is_active": False, "clicks": 5,
         "visitors": 4, "new_users": 3, "with_channel": 1, "posted": 1, "paid": 0, "created_at": None},
    ]
    for lang in ("uz", "ru", "en"):
        text = H.build_list_text(items, lang)
        T.check(f"[{lang}] ro'yxat: jami (bosish 45, yangi 23, post 9, to'lov 2)",
                "45" in text and "23" in text and "<b>9</b>" in text and "<b>2</b>" in text, text[:300])
        T.check(f"[{lang}] ro'yxat: HTML-escape", "Texno &lt;b&gt;kanal&lt;/b&gt;" in text and "<b>kanal</b>" not in text)
        T.check(f"[{lang}] ro'yxat: egasi va o'chirilgan belgisi", "777" in text and "⚪️" in text and "🟢" in text)
        T.check(f"[{lang}] bo'sh ro'yxat", "/link_new" in H.build_list_text([], lang))
        joins = [{"user_id": 55, "username": "vali", "full_name": "Vali <x>", "joined_at": None,
                  "has_channel": True, "posted": True, "paid": False}]
        d = H.build_detail_text(items[0], {"visitors": 30, "new_users": 20, "with_channel": 12, "posted": 8, "paid": 2},
                                joins, "PostAssistBot", lang)
        T.check(f"[{lang}] tafsilot: foizlar (60% / 40% / 10%)", "60%" in d and "40%" in d and "10%" in d, d[:400])
        T.check(f"[{lang}] tafsilot: kim kelgani (ism, @username, ID, belgilar)",
                "Vali &lt;x&gt;" in d and "@vali" in d and "<code>55</code>" in d and "📢📝" in d and "💎" not in d.split("Vali")[1])
        T.check(f"[{lang}] tafsilot: havola URL", "https://t.me/PostAssistBot?start=s_tech" in d)
        T.check(f"[{lang}] tafsilot: yangi yo'q -> foiz '—'",
                "—" in H.build_detail_text(items[0], {"visitors": 0, "new_users": 0, "with_channel": 0, "posted": 0, "paid": 0}, [], None, lang))
        my = H.build_my_text(items, "PostAssistBot", lang)
        T.check(f"[{lang}] /mylinks: havola va sonlar, shaxsiy ma'lumot yo'q", "s_tech" in my and "s_ali" in my and "Vali" not in my)
        T.check(f"[{lang}] /mylinks bo'sh", H.build_my_text([], None, lang) == links_t("tl_my_empty", lang))
        u = H.build_user_text(55, {"origin": {"code": "tech", "title": "T", "first_at": None},
                                   "visits": [{"code": "tech"}, {"code": "ali"}]}, lang)
        T.check(f"[{lang}] /link_user: qaysi havoladan kelgani", "tech" in u and "ali" in u)
        T.check(f"[{lang}] /link_user: havolasiz", H.build_user_text(55, None, lang) == links_t("tl_user_none", lang, user=55))
    many = [dict(items[0], id=i, code=f"k{i}") for i in range(30)]
    T.check("ro'yxat 15 tagacha qisqartiriladi", H.build_list_text(many, "uz").count("<code>k") == H.LIST_LIMIT)

    from translations.admin_panel import admin_t
    for lang in ("uz", "ru", "en"):
        body = admin_t("cmd_body", lang)
        T.check(f"[{lang}] /admin_help ichida yangi buyruqlar",
                all(c in body for c in ("/links", "/link_new", "/link_off", "/link_user")))


# ---------------------------------------------------------------- B. /start oqimi (soxta DB)

start_mod = importlib.import_module("handlers.start")
import database as db  # noqa: E402


class _Msg:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))


async def _run_start(args, link=None, is_new=True):
    calls, bg = [], []
    user = SimpleNamespace(id=NEW1, username="guest", full_name="Guest", first_name="Guest", language_code="uz")
    msg = _Msg()
    update = SimpleNamespace(effective_user=user, message=msg)

    class _Bot:
        async def send_message(self, **kw):
            pass
    context = SimpleNamespace(args=list(args), bot=_Bot(), user_data={}, chat_data={})

    async def fake_run_db(fn, *pos, **kw):
        calls.append((fn.__name__, pos, kw))
        if fn.__name__ == "get_link":
            return link
        if fn.__name__ == "save_user":
            return is_new
        return "uz"

    async def ok(*a):
        return True, []

    async def empty(*a):
        return ""

    async def none(*a):
        return None

    def run_bg(coro, **kw):
        bg.append(kw.get("name", ""))
        coro.close()

    with (patch.object(db, "run_db", fake_run_db),
          patch.object(start_mod, "peek_profile", return_value=None),
          patch.object(start_mod, "check_user_subscribed", ok),
          patch.object(start_mod, "get_smart_reply_ad_async", empty),
          patch.object(start_mod, "user_wants_simple_menu", none),
          patch.object(start_mod, "resolve_main_keyboard", none),
          patch.object(start_mod, "main_menu_intro_suffix", empty),
          patch.object(start_mod, "run_background_task", run_bg)):
        await start_mod.start(update, context)
    saves = [c for c in calls if c[0] == "save_user"]
    return saves[0][2].get("referrer_id") if saves else "NO_SAVE", bg, msg.replies


def start_flow() -> None:
    print("\n== B. /start oqimi (soxta DB) ==")
    owner_link = {"id": 7, "code": "ali", "owner_id": OWNER, "is_active": True}
    ref, bg, replies = asyncio.run(_run_start(["s_ali"], owner_link))
    T.check("egasi bor havola: yangi foydalanuvchi egasining taklifi", ref == OWNER, str(ref))
    T.check("tashrif fonda yoziladi", any(n.startswith("start:source-link:7") for n in bg), str(bg))
    T.check("egasiga «do'st qo'shildi» xabari (oddiy referal yo'li)", any(n.startswith("start:referrer-reward") for n in bg), str(bg))
    T.check("javob bitta (salomlashish)", len(replies) == 1)
    ref, bg, _ = asyncio.run(_run_start(["s_tech"], {"id": 8, "code": "tech", "owner_id": None, "is_active": True}))
    T.check("egasiz havola: taklif qiluvchi yo'q, lekin tashrif yoziladi",
            ref is None and any(n.startswith("start:source-link:8") for n in bg), f"{ref} {bg}")
    ref, bg, _ = asyncio.run(_run_start(["s_old"], {"id": 9, "code": "old", "owner_id": OWNER, "is_active": False}))
    T.check("o'chirilgan havola: hisobga olinmaydi, ball ham yo'q",
            ref is None and not any("source-link" in n for n in bg), f"{ref} {bg}")
    ref, bg, _ = asyncio.run(_run_start(["s_nope"], None))
    T.check("noma'lum havola: /start oddiy ishlaydi", ref is None and not any("source-link" in n for n in bg))
    ref, bg, _ = asyncio.run(_run_start(["s_BAD!"], owner_link))
    T.check("yaroqsiz kod: DB'ga ham bormaydi", ref is None)
    ref, bg, _ = asyncio.run(_run_start(["ref_123"], owner_link))
    T.check("eski ref_ havolasi buzilmagan", ref == 123)
    ref, bg, _ = asyncio.run(_run_start(["s_ali"], owner_link, is_new=False))
    T.check("eski foydalanuvchi bossa: tashrif bor, «do'st qo'shildi» yo'q",
            any("source-link" in n for n in bg) and not any("referrer-reward" in n for n in bg), str(bg))

    async def broken(fn, *a, **k):
        raise RuntimeError("db down")
    from handlers import tracked_links as H
    with patch.object(db, "run_db", broken):
        T.check("DB xatosida havola e'tiborsiz (start buzilmaydi)", asyncio.run(H.link_for_start("s_ali")) is None)


# ---------------------------------------------------------------- C. Real PostgreSQL

def online() -> None:
    print("\n== C. Real PostgreSQL ==")
    if not URL:
        T.skip("real PG", "sinov bazasi URL yo'q (MINIAPP_TEST_DATABASE_URL / pgserver)")
        return
    import psycopg2

    from repositories import tracked_links_repository as TL
    from services.referral_service import ReferralService

    db.init_db()
    conn = psycopg2.connect(URL)
    conn.autocommit = True
    cur = conn.cursor()

    def cleanup():
        cur.execute("DELETE FROM tracked_links WHERE code LIKE 'zt\\_%'")
        cur.execute("DELETE FROM tracked_link_visits WHERE user_id = ANY(%s)", (list(IDS),))
        cur.execute("DELETE FROM channels WHERE user_id = ANY(%s)", (list(IDS),))
        cur.execute("DELETE FROM payments WHERE user_id = ANY(%s)", (list(IDS),))
        cur.execute("DELETE FROM credits_ledger WHERE user_id = ANY(%s)", (list(IDS),))
        cur.execute("DELETE FROM users WHERE user_id = ANY(%s)", (list(IDS),))

    cleanup()
    TL._POST_CHECKED.clear()
    try:
        for uid, name in ((OWNER, "ali_smm_zt"), (OLD, "old_user_zt"), (ADM, "admin_zt")):
            cur.execute("INSERT INTO users (user_id, username, full_name, language_code, plan_type) VALUES (%s,%s,%s,'uz','free')",
                        (uid, name, f"Ism {uid}"))
        r = TL.create_link("zt_tech", "Texno kanal", None, ADM)
        T.check("havola yaratildi (egasiz)", r["ok"] and r["link"]["code"] == "zt_tech", str(r))
        r2 = TL.create_link(" ZT-Ali ", "Ali — hamkor", OWNER, ADM)
        T.check("havola yaratildi (egasi bilan, kod normallashtirildi)", r2["ok"] and r2["link"]["code"] == "zt_ali" and r2["link"]["owner_id"] == OWNER, str(r2))
        T.check("takror kod rad", TL.create_link("zt_tech", "x", None, ADM) == {"ok": False, "error": "exists"})
        T.check("noma'lum egasi rad", TL.create_link("zt_x", "x", 9_710_999_999, ADM) == {"ok": False, "error": "owner_unknown"})
        T.check("bo'sh nom rad", TL.create_link("zt_y", "   ", None, ADM) == {"ok": False, "error": "bad_title"})
        T.check("yaroqsiz kod rad", TL.create_link("!!", "x", None, ADM) == {"ok": False, "error": "bad_code"})
        T.check("egasini @username bo'yicha topish (katta-kichik harf farqsiz)", TL.find_user_id("@ALI_SMM_ZT") == OWNER)
        T.check("egasini ID bo'yicha topish / noma'lum -> None", TL.find_user_id(str(OWNER)) == OWNER and TL.find_user_id("@yoq_zt_user") is None)

        tech, ali = TL.get_link("zt_tech"), TL.get_link("ZT_ALI")
        # /start oqimi: egasi bor havola -> referrer_id = egasi (ReferralService qoidalari)
        res = ReferralService.register_new_user(NEW1, "new1_zt", full_name="Yangi Bir", referrer_id=ali["owner_id"], language_code="uz")
        T.check("yangi foydalanuvchi egasining taklifi sifatida saqlandi", res.get("is_new") and res.get("referrer_id") == OWNER, str(res))
        TL.record_visit(ali["id"], NEW1, True)
        TL.record_visit(ali["id"], NEW1, False)          # takror bosish
        TL.record_visit(tech["id"], NEW1, False)         # boshqa havolani ham bosdi (birinchi tegish o'zgarmaydi)
        ReferralService.register_new_user(NEW2, "new2_zt", full_name="Yangi Ikki", referrer_id=None, language_code="uz")
        TL.record_visit(tech["id"], NEW2, True)
        TL.record_visit(tech["id"], OLD, False)          # eski foydalanuvchi bosdi
        st_ali, st_tech = TL.link_stats(ali["id"]), TL.link_stats(tech["id"])
        T.check("ali: 1 noyob, 1 yangi", st_ali["visitors"] == 1 and st_ali["new_users"] == 1, str(st_ali))
        T.check("tech: 3 noyob (NEW1, NEW2, OLD), faqat 1 yangi", st_tech["visitors"] == 3 and st_tech["new_users"] == 1, str(st_tech))
        T.check("bosishlar takrorlar bilan (ali 2, tech 3)", TL.get_link("zt_ali")["clicks"] == 2 and TL.get_link("zt_tech")["clicks"] == 3)

        # faollik: kanal, post, to'lov
        T.check("hali kanal/post/to'lov yo'q", st_ali["with_channel"] == 0 and st_ali["posted"] == 0 and st_ali["paid"] == 0)
        cur.execute("INSERT INTO channels (user_id, channel_id, channel_title) VALUES (%s, %s, 'K')", (NEW2, "-100971000003"))
        T.check("birinchi post belgisi yozildi", TL.mark_first_post(NEW1) is True)
        T.check("ikkinchi chaqiruv DB'ga bormaydi (kesh)", TL.mark_first_post(NEW1) is False)
        T.check("havolasiz foydalanuvchi: belgi yo'q", TL.mark_first_post(OLD) is False)
        reward = ReferralService.register_first_action(NEW1, notify=False)
        T.check("ball havola EGASIGA yozildi (birinchi postdan keyin)", reward.get("granted") and reward.get("referrer_id") == OWNER, str(reward))
        cur.execute("SELECT COUNT(*) FROM credits_ledger WHERE user_id = %s AND operation_type = 'referral'", (OWNER,))
        T.check("egasining hisobida referal yozuvi bor", cur.fetchone()[0] == 1)
        cur.execute("UPDATE users SET plan_type = 'pro' WHERE user_id = %s", (NEW2,))
        st_ali, st_tech = TL.link_stats(ali["id"]), TL.link_stats(tech["id"])
        T.check("ali: post qilgan = kanal ulagan hisobida ham (1/1)", st_ali["posted"] == 1 and st_ali["with_channel"] == 1, str(st_ali))
        T.check("tech: kanal ulagan 1, to'lagan 1 (PRO), post 0", st_tech["with_channel"] == 1 and st_tech["paid"] == 1 and st_tech["posted"] == 0, str(st_tech))

        joins = TL.recent_joins(tech["id"])
        T.check("tech: ro'yxatda faqat shu havola bilan ro'yxatdan o'tgan NEW2", [j["user_id"] for j in joins] == [NEW2], str(joins))
        T.check("ro'yxat: ism, username, holat", joins[0]["username"] == "new2_zt" and joins[0]["has_channel"] and joins[0]["paid"])
        src = TL.source_of_user(NEW1)
        T.check("NEW1: kelgan havola zt_ali, bosganlari ikkalasi", src["origin"]["code"] == "zt_ali" and {v["code"] for v in src["visits"]} == {"zt_ali", "zt_tech"}, str(src))
        T.check("OLD: havola bilan ro'yxatdan o'tmagan", TL.source_of_user(OLD)["origin"] is None)
        T.check("havolasiz foydalanuvchi -> None", TL.source_of_user(ADM) is None)

        listed = {x["code"]: x for x in TL.list_links(200)}
        T.check("ro'yxat statistikasi to'g'ri", listed["zt_tech"]["new_users"] == 1 and listed["zt_ali"]["posted"] == 1, str(listed.get("zt_tech")))
        mine = TL.list_links(50, OWNER)
        T.check("/mylinks: egasi faqat o'z havolasini ko'radi", [x["code"] for x in mine] == ["zt_ali"])
        T.check("o'chirish", TL.set_active("zt_tech", False) and TL.get_link("zt_tech")["is_active"] is False)
        T.check("yoqish", TL.set_active("ZT_TECH", True) and TL.get_link("zt_tech")["is_active"] is True)
        T.check("noma'lum kodni o'chirish -> False", TL.set_active("zt_yoq", False) is False)
        db.init_db()
        T.check("init_db qayta ishlaydi (idempotent), ma'lumot saqlanadi", TL.get_link("zt_ali") is not None)
    finally:
        cleanup()
        conn.close()


def main() -> int:
    offline()
    start_flow()
    online()
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
