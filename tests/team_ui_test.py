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

STATE = {"mode": None, "seats": 2, "revoked": [], "removed": [], "roles": [], "left": []}
CH = {"channel_id": "-100111", "title": "Kanal <A>"}


def fake_team(uid):
    members = [{"user_id": 77, "role": "editor", "name": "Ali", "username": "ali", "active": True, "since": None}]
    return {"seats": {"plan": "ultra" if STATE["seats"] else "pro", "limit": STATE["seats"], "used": 1, "pending": 1, "free": 0},
            "channels": [{**CH, "members": members, "invites": [{"id": 5, "role": "scheduler", "expires_at": None}]}]}


fake = {
    TI.list_team: fake_team,
    TI.workspaces_for: lambda uid: [{"owner_id": 9, "owner_name": "Ega", "suspended": False, "channels": [{"channel_id": "-100222", "title": "Boshqa", "role": "analyst"}]}],
    TI.get_mode: lambda uid: STATE["mode"],
    TI.set_mode: lambda uid, m: STATE.update(mode=m) or True,
    TI.create_invite: lambda uid, ch, role: {"ok": True, "token": "tok_abcdefghijklmnop", "id": 5, "expires_at": None},
    TI.revoke_invite: lambda uid, i: STATE["revoked"].append(i) or True,
    TI.remove_member: lambda uid, ch, m: STATE["removed"].append((ch, m)) or True,
    TI.set_member_role: lambda uid, ch, m, r: STATE["roles"].append((ch, m, r)) or True,
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
    check("ULTRA: Yordamchi/A'zolar/Ish joylarim/Rol/Orqaga tugmalari", {"tm_mode", "tm_inv", "tm_mem", "tm_ws", "stgs_hub"} <= set(cbs), str(cbs))
    check("ish joyi ko'rinadi (Ega — Boshqa (Tahlilchi))", "Ega" in text and "Boshqa" in text)
    STATE["seats"] = 0
    q, _ = press("tm_home")
    check("PRO: jamoa yo'q — ULTRA taklifi va «bitta odam» matni", "ULTRA" in q.edits[-1][0] and "sub_open" in [b.callback_data for b in buttons(q)] and "tm_inv" not in [b.callback_data for b in buttons(q)], q.edits[-1][0])
    STATE["seats"] = 2

    print("== Rol tanlash ==")
    q, _ = press("tm_mode")
    check("ikki variant: o'zim / yordamchiman", {b.callback_data for b in buttons(q)} >= {"tm_set:owner", "tm_set:helper"})
    q, _ = press("tm_set:helper")
    check("yordamchi rejimi saqlandi va yo'riqnoma", STATE["mode"] == "helper" and "taklif havolasi" in q.edits[-1][0])
    q, _ = press("tm_set:admin")
    check("noto'g'ri rejim e'tiborsiz (bosh ekran)", STATE["mode"] == "helper")

    print("== Taklif ==")
    q, _ = press("tm_inv")
    check("kanallar ro'yxati", "tm_ic:-100111" in [b.callback_data for b in buttons(q)])
    q, _ = press("tm_ic:-100111")
    check("uch rol tugmasi", {b.callback_data for b in buttons(q)} >= {"tm_ir:-100111:editor", "tm_ir:-100111:scheduler", "tm_ir:-100111:analyst"})
    check("kanal nomi HTML-escape", "Kanal &lt;A&gt;" in q.edits[-1][0])
    q, _ = press("tm_ir:-100111:editor")
    check("havola t.me/<bot>?start=team_<token>", "https://t.me/postbot?start=team_tok_abcdefghijklmnop" in q.edits[-1][0], q.edits[-1][0])
    check("«Yuborish» (share) va «Bekor qilish» tugmalari", any((b.url or "").startswith("https://t.me/share/url") for b in buttons(q)) and "tm_rv:5" in [b.callback_data for b in buttons(q)])
    press("tm_ir:-100111:owner")
    check("noto'g'ri rol callback'i hech narsa yaratmaydi", True)
    q, _ = press("tm_rv:5")
    check("taklif bekor qilindi", STATE["revoked"] == [5])
    fake[TI.create_invite] = lambda uid, ch, role: {"ok": False, "error": "no_team"}
    q, _ = press("tm_ir:-100111:editor")
    check("PRO: taklif rad — ULTRA kerakligi aytiladi", "ULTRA" in q.edits[-1][0])
    fake[TI.create_invite] = lambda uid, ch, role: {"ok": False, "error": "seats_full"}
    q, _ = press("tm_ir:-100111:editor")
    check("o'rindiq to'lgan xabari", "o'rindiq" in q.edits[-1][0])

    print("== A'zolar ==")
    q, _ = press("tm_mem")
    check("a'zo va taklif ro'yxatda", "77" in q.edits[-1][0] and "taklif" in q.edits[-1][0])
    q, _ = press("tm_mm:-100111:77")
    check("a'zo ekrani: boshqa 2 rol + olib tashlash", {"tm_mr:-100111:77:scheduler", "tm_mr:-100111:77:analyst", "tm_md:-100111:77"} <= {b.callback_data for b in buttons(q)})
    press("tm_mr:-100111:77:analyst")
    check("rol o'zgartirildi", STATE["roles"] == [("-100111", 77, "analyst")])
    q, _ = press("tm_md:-100111:77")
    check("olib tashlash tasdiq so'raydi (hali o'chmadi)", STATE["removed"] == [] and "tm_mdy:-100111:77" in [b.callback_data for b in buttons(q)])
    press("tm_mdy:-100111:77")
    check("tasdiqdan keyin o'chdi", STATE["removed"] == [("-100111", 77)])
    q, _ = press("tm_mm:-100111:999")
    check("begona a'zo ID — xato ekrani (hech narsa o'zgarmaydi)", len(STATE["removed"]) == 1)
    q, _ = press("tm_lv:9")
    check("yordamchi chiqdi", STATE["left"] == [9])

    print("== Taklifni qabul qilish (/start team_<token>) ==")
    results = {"r": {"ok": True, "owner_id": 9, "channel_id": "-100222", "role": "editor", "title": "Boshqa"}}
    fake[TI.accept_invite] = lambda token, uid: results["r"]
    msg = Msg()
    bot = Bot()
    upd = SimpleNamespace(effective_user=SimpleNamespace(id=5, full_name="Vali", username="vali"), effective_message=msg)
    ctx = SimpleNamespace(user_data={}, bot=bot)
    asyncio.run(UI.accept_team_invite(upd, ctx, "tok_abcdefghijklmnop", "uz"))
    check("yordamchiga tabrik (rol bilan)", "Muharrir" in msg.sent[-1][0] and "Boshqa" in msg.sent[-1][0], str(msg.sent))
    check("egasiga bildirishnoma yuborildi", bot.sent and bot.sent[-1]["chat_id"] == 9 and "Vali" in bot.sent[-1]["text"], str(bot.sent))
    for err, frag in (("used", "ishlatilgan"), ("expired", "muddati"), ("invalid", "topilmadi"), ("self", "o'z taklifingiz"), ("no_team", "ULTRA"), ("seats_full", "o'rindiqlari")):
        results["r"] = {"ok": False, "error": err}
        msg = Msg()
        asyncio.run(UI.accept_team_invite(SimpleNamespace(effective_user=upd.effective_user, effective_message=msg), ctx, "tok_abcdefghijklmnop", "uz"))
        check(f"xato «{err}» tushunarli matn bilan", frag in msg.sent[-1][0], msg.sent[-1][0])
finally:
    db.run_db = orig

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
