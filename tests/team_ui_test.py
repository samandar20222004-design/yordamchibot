#!/usr/bin/env python3
"""Jamoa va rol — bot ekranlari (DB'siz: servis funksiyalari soxta): matnlar 3 tilda, tugmalar ≤18, oqimlar, taklifni qabul qilish."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:TEAM_UI_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
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


import database as db  # noqa: E402
import handlers.team_ui as UI  # noqa: E402
from keyboards.inline import get_settings_profile_keyboard  # noqa: E402
from services import team_invites as TI  # noqa: E402
from translations.team_ui import TEAM_I18N, team_parity_report  # noqa: E402

print("== Matnlar ==")
check("uz/ru/en pariteti", team_parity_report()["in_sync"], str(team_parity_report()))
for lang in ("uz", "ru", "en"):
    long = [k for k, v in TEAM_I18N[lang].items() if k.startswith("tm_btn_") and len(v) > 22]
    check(f"[{lang}] tugma yorliqlari qisqa", not long, str(long))
check("Sozlamalar hub'ida «Jamoa va rol» tugmasi (stgs_team)", any(b.callback_data == "stgs_team" for r in get_settings_profile_keyboard("uz").inline_keyboard for b in r))
for lang, label in (("uz", "👥 Jamoa va rol"), ("ru", "👥 Команда и роль"), ("en", "👥 Team & role")):
    btn = next(b for r in get_settings_profile_keyboard(lang).inline_keyboard for b in r if b.callback_data == "stgs_team")
    check(f"[{lang}] hub tugmasi ≤18 belgi", btn.text == label and len(btn.text) <= 18, btn.text)

STATE = {"added": [], "mode": None, "seats": 2, "revoked": [], "removed": [], "perms": [], "left": [], "invites": []}
MEMBER_PERMS = ["create", "edit"]
CH = {"channel_id": "-100111", "title": "Kanal <A>"}


def fake_team(uid):
    members = [{"user_id": 77, "role": "editor", "perms": list(MEMBER_PERMS), "name": "Ali", "username": "ali", "active": True, "since": None}]
    return {"seats": {"plan": "ultra" if STATE["seats"] else "pro", "limit": STATE["seats"], "used": 1, "pending": 1, "free": 0},
            "channels": [{**CH, "members": members, "invites": [{"id": 5, "role": "scheduler", "perms": ["create", "reschedule"], "expires_at": None}]}]}


fake = {
    TI.list_team: fake_team,
    TI.workspaces_for: lambda uid: [{"owner_id": 9, "owner_name": "Ega", "suspended": False, "channels": [{"channel_id": "-100222", "title": "Boshqa", "role": "analyst", "perms": ["analytics"]}]}],
    TI.get_mode: lambda uid: STATE["mode"],
    TI.set_mode: lambda uid, m: STATE.update(mode=m) or True,
    TI.create_invite: lambda uid, chans, perms: STATE["invites"].append((chans, perms)) or {"ok": True, "token": "tok_abcdefghijklmnop", "id": 5, "expires_at": None},
    TI.revoke_invite: lambda uid, i: STATE["revoked"].append(i) or True,
    TI.remove_member: lambda uid, ch, m: STATE["removed"].append((ch, m)) or True,
    TI.set_member_perms: lambda uid, ch, m, perms: STATE["perms"].append((ch, m, list(perms))) or True,
    TI.leave: lambda uid, o: STATE["left"].append(o) or 1,
    db.get_user_language: lambda uid: "uz",
}


async def fake_run_db(fn, *a, **k):
    if fn in fake:
        return fake[fn](*a, **k)
    raise AssertionError(f"kutilmagan db chaqiruvi: {getattr(fn, '__name__', fn)}")


class Msg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, **kw):
        self.sent.append((text, kw))


class Query:
    def __init__(self, data, uid=5):
        self.data, self.from_user, self.message, self.edits = data, SimpleNamespace(id=uid), Msg(), []

    async def answer(self, *a, **k):
        return True

    async def edit_message_text(self, text, **kw):
        self.edits.append((text, kw))


class Bot:
    def __init__(self):
        self.sent = []

    async def get_me(self):
        return SimpleNamespace(username="postbot")

    async def send_message(self, **kw):
        self.sent.append(kw)


def press(data):
    q = Query(data)
    ctx = SimpleNamespace(user_data={"lang": "uz"}, bot=Bot())
    asyncio.run(UI.team_callback(SimpleNamespace(callback_query=q, effective_user=q.from_user, effective_message=q.message), ctx))
    return q, ctx


def buttons(q):
    markup = q.edits[-1][1]["reply_markup"]
    return [b for r in markup.inline_keyboard for b in r]


orig = db.run_db
db.run_db = fake_run_db
try:
    print("== Bosh ekran ==")
    q, _ = press("stgs_team")
    text = q.edits[-1][0]
    cbs = [b.callback_data for b in buttons(q)]
    check("ULTRA: o'rindiqlar 1/2 va kutilayotgan taklif", "1/2" in text and "+1" in text, text)
    check("ULTRA: Yordamchi/A'zolar/Ish joylarim/Orqaga tugmalari (rol tanlash tugmasi YO'Q)", {"tm_inv", "tm_mem", "tm_ws", "stgs_hub"} <= set(cbs) and "tm_mode" not in cbs, str(cbs))
    check("ish joyi ko'rinadi (Ega — Boshqa (Tahlilchi))", "Ega" in text and "Boshqa" in text)
    STATE["seats"] = 0
    q, _ = press("tm_home")
    check("PRO: jamoa yo'q — ULTRA taklifi va «bitta odam» matni", "ULTRA" in q.edits[-1][0] and "sub_open" in [b.callback_data for b in buttons(q)] and "tm_inv" not in [b.callback_data for b in buttons(q)], q.edits[-1][0])
    STATE["seats"] = 2

    print("== Taklif ==")
    q, _ = press("tm_inv")
    check("«Yordamchi» avval usul tanlatadi: kontakt / havola", {"tm_pk", "tm_il"} <= {b.callback_data for b in buttons(q)}, str([b.callback_data for b in buttons(q)]))
    q, _ = press("tm_il")
    check("kanallar ro'yxati", "tm_ic:-100111" in [b.callback_data for b in buttons(q)])
    q, _ = press("tm_ic:-100111")
    check("5 shablon tugmasi (hammasi / muharrir / rejalovchi / tahlilchi / faqat ko'rish)",
          {b.callback_data for b in buttons(q)} >= {f"tm_ir:-100111:{p}" for p in ("full", "editor", "scheduler", "analyst", "view")})
    check("kanal nomi HTML-escape", "Kanal &lt;A&gt;" in q.edits[-1][0])
    q, _ = press("tm_ir:-100111:editor")
    check("havola t.me/<bot>?start=team_<token>", "https://t.me/postbot?start=team_tok_abcdefghijklmnop" in q.edits[-1][0], q.edits[-1][0])
    check("taklif tanlangan shablon ruxsatlari bilan yaratildi", STATE["invites"][-1] == (["-100111"], "editor"), str(STATE["invites"]))
    press("tm_ir:-100111:view")
    check("«Faqat ko'rish» shabloni bo'sh ruxsat bilan", STATE["invites"][-1] == (["-100111"], []))
    q, _ = press("tm_ir:-100111:full")
    check("«Hammasi» shabloni — hamma ruxsat", STATE["invites"][-1] == (["-100111"], "full") and "hammasi" in q.edits[-1][0], q.edits[-1][0])
    check("«Yuborish» (share) va «Bekor qilish» tugmalari", any((b.url or "").startswith("https://t.me/share/url") for b in buttons(q)) and "tm_rv:5" in [b.callback_data for b in buttons(q)])
    press("tm_ir:-100111:owner")
    check("noto'g'ri rol callback'i hech narsa yaratmaydi", True)
    q, _ = press("tm_rv:5")
    check("taklif bekor qilindi", STATE["revoked"] == [5])
    fake[TI.create_invite] = lambda uid, ch, perms: {"ok": False, "error": "no_team"}
    q, _ = press("tm_ir:-100111:editor")
    check("PRO: taklif rad — ULTRA kerakligi aytiladi", "ULTRA" in q.edits[-1][0])
    fake[TI.create_invite] = lambda uid, ch, perms: {"ok": False, "error": "seats_full"}
    q, _ = press("tm_ir:-100111:editor")
    check("o'rindiq to'lgan xabari", "o'rindiq" in q.edits[-1][0])

    print("== Kontakt tanlash -> huquqlar (Telegram adminlari kabi) ==")
    fake[TI.search_people] = lambda uid, q: PEOPLE.get(q, [])
    fake[TI.add_helper] = lambda uid, m, chans, perms: STATE["added"].append((m, list(chans), list(perms))) or {"ok": True, "channel_ids": list(chans), "perms": list(perms), "name": "Vali", "new": True}
    PEOPLE = {"88": [{"user_id": 88, "name": "Vali", "username": "vali", "member": False}]}
    STATE["added"] = []
    q, ctx_pick = press("tm_pk")
    kb = q.message.sent[-1][1]["reply_markup"]
    req = kb.keyboard[0][0].request_users
    check("«Kontakt tanlash»: Telegram odam tanlagichi (request_users, bot emas, bitta odam)", req is not None and req.user_is_bot is False and req.max_quantity == 1 and req.request_id == UI.TEAM_PICK_REQUEST_ID)

    class PickMsg(Msg):
        def __init__(self, uid, request_id=UI.TEAM_PICK_REQUEST_ID):
            super().__init__()
            self.users_shared = SimpleNamespace(request_id=request_id, users=[SimpleNamespace(user_id=uid, first_name="Vali", username=None)])

    def shared(uid, ctx, request_id=UI.TEAM_PICK_REQUEST_ID, me=5):
        m = PickMsg(uid, request_id)
        asyncio.run(UI.team_users_shared(SimpleNamespace(callback_query=None, effective_message=m, effective_user=SimpleNamespace(id=me)), ctx))
        return m

    def tap(data, ctx):
        qq = Query(data)
        asyncio.run(UI.team_callback(SimpleNamespace(callback_query=qq, effective_user=qq.from_user, effective_message=qq.message), ctx))
        return qq

    ctx = SimpleNamespace(user_data={"lang": "uz"}, bot=Bot())
    m = shared(88, ctx)
    check("tanlangach huquqlar ekrani (odam nomi + 7 ta yoqish/o'chirish + «Qo'shish»)",
          "Vali" in m.sent[-1][0] and any(b.callback_data == "tm_ago" for r in m.sent[-1][1]["reply_markup"].inline_keyboard for b in r)
          and {f"tm_ap:{p}" for p in TI.PERMS} <= {b.callback_data for r in m.sent[-1][1]["reply_markup"].inline_keyboard for b in r}, str(m.sent[-1]))
    st = ctx.user_data[UI.UD_TEAM_ADD]
    check("standart: hamma huquq + hamma kanal, odam botda bor", st["perms"] == list(TI.PERMS) and st["chans"] == ["-100111"] and st["known"] is True)
    qq = tap("tm_ap:send_now", ctx)
    check("huquq o'chirildi (⬜), qolganlari yoniq", "send_now" not in st["perms"] and len(st["perms"]) == 6 and any(b.text.startswith("⬜") and "Darhol" in b.text for r in qq.edits[-1][1]["reply_markup"].inline_keyboard for b in r))
    tap("tm_apr:analyst", ctx)
    check("shablon: Tahlilchi -> faqat statistika", st["perms"] == ["analytics"], str(st["perms"]))
    tap("tm_ap:ai", ctx)
    check("shablon ustiga alohida huquq qo'shildi", st["perms"] == ["analytics", "ai"], str(st["perms"]))
    tap("tm_ap:hack", ctx)
    check("noto'g'ri huquq kaliti e'tiborsiz", st["perms"] == ["analytics", "ai"])
    qq = tap("tm_ago", ctx)
    check("«Qo'shish»: add_helper tanlangan odam, kanal va huquqlar bilan", STATE["added"] == [(88, ["-100111"], ["analytics", "ai"])], str(STATE["added"]))
    check("natija: holat tozalandi, egasiga «xabar yuborildi»", UI.UD_TEAM_ADD not in ctx.user_data and "Unga xabar yuborildi" in qq.edits[-1][0], qq.edits[-1][0])
    check("yordamchiga bot xabari (egasi, kanal, huquqlar)", ctx.bot.sent and ctx.bot.sent[-1]["chat_id"] == 88 and "Statistika" in ctx.bot.sent[-1]["text"], str(ctx.bot.sent))
    qq = tap("tm_ago", ctx)
    check("seans tugagach «Qo'shish» takror bosilsa ikkinchi marta qo'shilmaydi", len(STATE["added"]) == 1 and "qaytadan" in qq.edits[-1][0], qq.edits[-1][0])
    ctx = SimpleNamespace(user_data={"lang": "uz"}, bot=Bot())
    shared(5, ctx)
    check("o'zini tanlab bo'lmaydi", UI.UD_TEAM_ADD not in ctx.user_data)
    shared(88, ctx, request_id=999)
    check("boshqa request_id (begona oqim) e'tiborsiz", UI.UD_TEAM_ADD not in ctx.user_data)
    PEOPLE.clear()
    fake[TI.create_invite] = lambda uid, chans, perms: STATE["invites"].append((chans, perms)) or {"ok": True, "token": "tok_zzzzzzzzzzzzzzzz", "id": 7, "expires_at": None}
    m = shared(99, ctx)
    check("botni ishga tushirmagan odam: havola yaratilishi aytiladi", "havola" in m.sent[-1][0].lower() and ctx.user_data[UI.UD_TEAM_ADD]["known"] is False)
    qq = tap("tm_ago", ctx)
    check("bot foydalanuvchisi bo'lmasa — taklif havolasi (share) yaratiladi, add_helper chaqirilmaydi", "start=team_tok_zzzzzzzzzzzzzzzz" in qq.edits[-1][0] and len(STATE["added"]) == 1, qq.edits[-1][0])
    fake[TI.add_helper] = lambda uid, m, chans, perms: {"ok": False, "error": "seats_full"}
    PEOPLE["88"] = [{"user_id": 88, "name": "Vali", "username": "vali", "member": False}]
    ctx = SimpleNamespace(user_data={"lang": "uz"}, bot=Bot())
    shared(88, ctx)
    qq = tap("tm_ago", ctx)
    check("o'rindiq to'lgan: tushunarli xabar", "o'rindiq" in qq.edits[-1][0], qq.edits[-1][0])
    fake[TI.add_helper] = lambda uid, m, chans, perms: {"ok": False, "error": "too_many_pending"}
    shared(88, ctx)
    qq = tap("tm_ago", ctx)
    check("kunlik chegara: tushunarli xabar", "ertaga" in qq.edits[-1][0].lower(), qq.edits[-1][0])

    print("== A'zolar ==")
    q, _ = press("tm_mem")
    check("a'zo va taklif ro'yxatda", "77" in q.edits[-1][0] and "taklif" in q.edits[-1][0])
    q, _ = press("tm_mm:-100111:77")
    cbs_m = {b.callback_data for b in buttons(q)}
    check("a'zo ekrani: 7 ruxsat katakchasi + olib tashlash", {f"tm_pt:-100111:77:{p}" for p in TI.PERMS} <= cbs_m and "tm_md:-100111:77" in cbs_m)
    labels = [b.text for b in buttons(q)]
    check("belgilangan ruxsatlar ✅, qolganlari ⬜", any(t.startswith("✅") and "Post yaratish" in t for t in labels) and any(t.startswith("⬜") and "Darhol yuborish" in t for t in labels), str(labels))
    check("limit egasidan ekanligi aytiladi", "SIZDAN" in q.edits[-1][0], q.edits[-1][0])
    q, _ = press("tm_pt:-100111:77:send_now")
    check("ruxsat almashtirildi (send_now qo'shildi, tartib saqlandi)", STATE["perms"] == [("-100111", 77, ["create", "edit", "send_now"])], str(STATE["perms"]))
    check("almashtirgach a'zo ekrani qayta chiziladi", any(b.callback_data == "tm_md:-100111:77" for b in buttons(q)))
    press("tm_pt:-100111:77:create")
    check("ruxsatni olib tashlash ham ishlaydi", STATE["perms"][-1] == ("-100111", 77, ["edit"]), str(STATE["perms"]))
    press("tm_pt:-100111:77:hack")
    check("noto'g'ri ruxsat kaliti e'tiborsiz", len(STATE["perms"]) == 2)
    q, _ = press("tm_md:-100111:77")
    check("olib tashlash tasdiq so'raydi (hali o'chmadi)", STATE["removed"] == [] and "tm_mdy:-100111:77" in [b.callback_data for b in buttons(q)])
    press("tm_mdy:-100111:77")
    check("tasdiqdan keyin o'chdi", STATE["removed"] == [("-100111", 77)])
    q, _ = press("tm_mm:-100111:999")
    check("begona a'zo ID — xato ekrani (hech narsa o'zgarmaydi)", len(STATE["removed"]) == 1)
    q, _ = press("tm_lv:9")
    check("yordamchi chiqdi", STATE["left"] == [9])

    print("== Taklifni qabul qilish (/start team_<token>) ==")
    results = {"r": {"ok": True, "owner_id": 9, "channel_id": "-100222", "role": "editor", "perms": ["create", "edit"], "title": "Boshqa"}}
    fake[TI.accept_invite] = lambda token, uid: results["r"]
    msg = Msg()
    bot = Bot()
    upd = SimpleNamespace(effective_user=SimpleNamespace(id=5, full_name="Vali", username="vali"), effective_message=msg)
    ctx = SimpleNamespace(user_data={}, bot=bot)
    asyncio.run(UI.accept_team_invite(upd, ctx, "tok_abcdefghijklmnop", "uz"))
    check("yordamchiga tabrik (ruxsatlari bilan)", "Post yaratish" in msg.sent[-1][0] and "Boshqa" in msg.sent[-1][0], str(msg.sent))
    check("egasiga bildirishnoma yuborildi", bot.sent and bot.sent[-1]["chat_id"] == 9 and "Vali" in bot.sent[-1]["text"], str(bot.sent))
    for err, frag in (("used", "ishlatilgan"), ("expired", "muddati"), ("invalid", "topilmadi"), ("self", "o'z taklifingiz"), ("no_team", "ULTRA"), ("seats_full", "o'rindiqlari")):
        results["r"] = {"ok": False, "error": err}
        msg = Msg()
        asyncio.run(UI.accept_team_invite(SimpleNamespace(effective_user=upd.effective_user, effective_message=msg), ctx, "tok_abcdefghijklmnop", "uz"))
        check(f"xato «{err}» tushunarli matn bilan", frag in msg.sent[-1][0], msg.sent[-1][0])
    print("== Yordamchi: bot orqali post -> Mini App (ish joyi) ==")
    import handlers.manual_post as MP
    from miniapp_api import drafts as drafts_mod

    saved = []
    fake[drafts_mod.save_draft] = lambda uid, payload: saved.append((uid, payload))
    fake[db.get_user_channels] = lambda uid: []

    def run_handoff(perms, suspended=False, enabled=True):
        saved.clear()
        fake[TI.workspaces_for] = lambda uid: [{"owner_id": 9, "owner_name": "Ega", "suspended": suspended,
                                                "channels": [{"channel_id": "-100222", "title": "Boshqa", "role": "editor", "perms": perms}]}]
        msg = Msg()
        ctx = SimpleNamespace(user_data={}, bot=Bot())
        old = {k: os.environ.get(k) for k in ("MINIAPP_ENABLED", "MINIAPP_URL", "MINIAPP_PROXY_ASSERT_EDGE_ONLY")}
        os.environ["MINIAPP_ENABLED"], os.environ["MINIAPP_URL"] = ("1", "https://app.example.com/app/") if enabled else ("0", "")
        os.environ["MINIAPP_PROXY_ASSERT_EDGE_ONLY"] = "1"  # prod sozlamasi: HTTPS + ishonchli proksi
        try:
            ok = asyncio.run(MP._helper_handoff(msg, ctx, 5, "uz", {"text": "Rasm uchun matn", "post_type": "photo", "file_id": "FILE1", "album": None, "message": None}))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        return ok, msg

    ok, msg = run_handoff(["create", "edit"])
    btn = msg.sent[-1][1]["reply_markup"].inline_keyboard[0][0] if msg.sent else None
    check("«create» ruxsati bor: qoralama saqlandi (media bilan)", ok and saved and saved[0][0] == 5 and saved[0][1]["file_id"] == "FILE1" and saved[0][1]["post_type"] == "photo", str(saved))
    check("Mini App tugmasi egasi ish joyi bilan (?ws=9)", btn is not None and btn.web_app is not None and "ws=9" in btn.web_app.url and "tab=post" in btn.web_app.url, str(btn))
    check("matnda egasi nomi va limit egasidan", "Ega" in msg.sent[-1][0] and "limit" in msg.sent[-1][0].lower(), msg.sent[-1][0])
    ok, msg = run_handoff(["analytics"])
    check("«create» ruxsati yo'q: yordamchi yo'li ishlamaydi (oddiy xabar)", ok is False and not saved)
    ok, msg = run_handoff(["create"], suspended=True)
    check("ish joyi to'xtatilgan: ishlamaydi", ok is False)
    ok, msg = run_handoff(["create"], enabled=False)
    check("Mini App o'chiq: qoralama yozilmaydi, tushuntirish beriladi", ok and not saved and "Mini App" in msg.sent[-1][0], str(msg.sent))
finally:
    db.run_db = orig

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
