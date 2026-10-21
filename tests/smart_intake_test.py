#!/usr/bin/env python3
"""Aqlli qabul: menyu tashqarisidagi xabar uchun AI O'ZI ishlamaydi — «Bu bilan nima qilamiz?» (DB'siz)."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
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


import database as db_mod  # noqa: E402
import handlers.image_post as image_post  # noqa: E402
import handlers.manual_post as mp  # noqa: E402
import handlers.smart_intake as si  # noqa: E402
import utils.helpers as helpers  # noqa: E402
from handlers.magic_post import MAGIC_STYLE_SELECT  # noqa: E402
from translations import content_menu_t  # noqa: E402

UID = 9001
CHANNELS = [(-1001, "Kanal A")]
run = asyncio.run


class Msg:
    def __init__(self, text=None, photo=None, video=None, caption=None, group=None):
        self.text, self.caption = text, caption
        self.photo = [SimpleNamespace(file_id=photo)] if photo else None
        self.video = SimpleNamespace(file_id=video) if video else None
        self.animation = self.document = None
        self.media_group_id = group
        self.chat_id = UID
        self.from_user = SimpleNamespace(id=UID)
        self.sent = []

    async def reply_text(self, text, **kw):
        self.sent.append(dict(text=text, **kw))
        return SimpleNamespace(message_id=1, chat=SimpleNamespace(id=UID))

    async def reply_photo(self, photo, **kw):
        self.sent.append(dict(photo=photo, **kw))

    async def reply_video(self, video, **kw):
        self.sent.append(dict(video=video, **kw))

    async def delete(self):
        self.deleted = True

    chat = SimpleNamespace(id=UID)


def upd(msg):
    return SimpleNamespace(message=msg, effective_message=msg, effective_user=msg.from_user, callback_query=None)


class Query:
    def __init__(self, data, message):
        self.data, self.message, self.from_user = data, message, message.from_user

    async def answer(self, *a, **k):
        pass

    async def edit_message_text(self, *a, **k):
        pass

    async def edit_message_reply_markup(self, **k):
        pass


def qupd(q):
    return SimpleNamespace(message=None, effective_message=q.message, effective_user=q.from_user, callback_query=q)


def ctx():
    return SimpleNamespace(user_data={"lang": "uz"}, chat_data={}, bot=SimpleNamespace(username="b"), application=None)


async def fake_run_db(fn, *a, **k):
    if getattr(fn, "__name__", "") == "get_user_channels":
        return list(CHANNELS)
    return None


db_mod.run_db = fake_run_db
mp.db.run_db = fake_run_db


async def _noop(**k):
    return None


def cbs(m):
    return [b.callback_data for r in m["reply_markup"].inline_keyboard for b in r]


print("== Matn: AI ishlamaydi, taklif chiqadi ==")
c = ctx()
m = Msg(text="Ertaga soat 10 da aksiya boshlanadi")
ok = run(si.offer_intake(upd(m), c, "uz"))
check("matn uchun taklif yuborildi", ok and len(m.sent) == 1)
check("tugmalar: post, AI, yopish", cbs(m.sent[0]) == ["in_post", "in_ai", "in_close"], str(cbs(m.sent[0])))
for short in ("ha", "???", "rahmat", "/start now please"):
    check(f"qisqa/buyruq «{short}» taklif BERMAYDI", not run(si.offer_intake(upd(Msg(text=short)), ctx(), "uz")))

print("== 📝 Post qilish: matn o'zgarmasdan preview ==")
si._CACHE.clear()
m = Msg(text="Ertaga soat 10 da aksiya boshlanadi")
run(si.offer_intake(upd(m), ctx(), "uz"))
c = ctx()
q = Query("in_post", m)
state = run(si.intake_callback(qupd(q), c))
check("MANUAL_PREVIEW holatiga o'tdi", state == mp.MANUAL_PREVIEW, str(state))
check("matn aynan saqlandi", c.user_data.get(mp.UD_CONTENT) == "Ertaga soat 10 da aksiya boshlanadi")
check("bitta kanal avtomatik tanlandi", mp._get_selected_channel(c) is not None)

print("== Rasm: Vision O'ZI ishlamaydi ==")
calls = []


async def fake_image(update, context):
    calls.append(update.message)
    return 777


image_post.image_photo_received = fake_image
helpers.send_no_channel_media_guide = lambda *a, **k: _false()


async def _false():
    return False


si._CACHE.clear()
p = Msg(photo="PH1", caption="Yangi mahsulot")
state = run(si.photo_intake_entry(upd(p), ctx()))
check("Vision chaqirilmadi", calls == [])
check("rasm uchun taklif chiqdi (post, AI, yopish)", len(p.sent) == 1 and cbs(p.sent[0]) == ["in_post", "in_ai", "in_close"])
check("rasm taklifi matni to'g'ri", p.sent[0]["text"] == content_menu_t("in_offer_photo", "uz"))
c = ctx()
state = run(si.intake_callback(qupd(Query("in_post", p)), c))
check("rasm o'zgarishsiz post preview'iga tushdi",
      state == mp.MANUAL_PREVIEW and c.user_data.get(mp.UD_FILE_ID) == "PH1"
      and c.user_data.get(mp.UD_POST_TYPE) == "photo" and c.user_data.get(mp.UD_CONTENT) == "Yangi mahsulot")
check("Vision hamon chaqirilmagan", calls == [])
si._CACHE.clear()
p = Msg(photo="PH2")
run(si.photo_intake_entry(upd(p), ctx()))
state = run(si.intake_callback(qupd(Query("in_ai", p)), ctx()))
check("✨ AI bosilgandagina Vision ishladi (1 marta)", len(calls) == 1 and state == 777)

print("== Video / yopish / eskirgan ==")
si._CACHE.clear()
v = Msg(video="VD1")
run(si.offer_intake(upd(v), ctx(), "uz"))
check("video: AI tugmasi yo'q", cbs(v.sent[0]) == ["in_post", "in_close"], str(cbs(v.sent[0])))
state = run(si.intake_callback(qupd(Query("in_close", v)), SimpleNamespace(
    user_data={"lang": "uz"}, bot=SimpleNamespace(send_message=_noop), application=None)))
check("yopish: hech narsa qilinmadi (END)", state == -1 and UID not in si._CACHE)
si._CACHE.clear()
state = run(si.intake_callback(qupd(Query("in_post", v)), ctx()))
check("eskirgan taklif: END, xato yo'q", state == -1)
si._CACHE[UID] = ({"kind": "text", "text": "x" * 20, "post_type": "text", "file_id": None, "album": None, "message": v}, 0)
check("TTL: 20 daqiqadan eski xabar olinmaydi", si.peek(UID) is None)


print("== Matn AI: faqat bosilganda uslub tanlash ==")
si._CACHE.clear()
m = Msg(text="Yangi kofeyna ochildi, birinchi mijozlarga chegirma bor")
run(si.offer_intake(upd(m), ctx(), "uz"))
c = ctx()
state = run(si.intake_callback(qupd(Query("in_ai", m)), c))
check("in_ai → MAGIC_STYLE_SELECT", state == MAGIC_STYLE_SELECT, str(state))
check("matn Magic sessiyasiga o'tdi", c.user_data.get("magic_raw_text", "").startswith("Yangi kofeyna"))

print("== Yorliqlar 3 tilda <= 18 belgi ==")
for lang in ("uz", "ru", "en"):
    for k in ("in_btn_post", "in_btn_ai_text", "in_btn_ai_photo", "in_btn_close"):
        t = content_menu_t(k, lang)
        check(f"[{lang}] {k} = «{t}» <= 18", len(t) <= 18)

print(f"\n JAMI: o'tdi={passed}, xato={failed}")
sys.exit(1 if failed else 0)
