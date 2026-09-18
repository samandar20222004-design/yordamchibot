#!/usr/bin/env python3
"""SMART EMOJI VA SMART URL PARSER — 2-QISM BUGFIX TESTI.

Tekshiradi:
  1) Reaksiyalar oynasida (MANUAL_PREVIEW) foydalanuvchi to'g'ridan-to'g'ri emoji yuborsa
     (masalan 😎 yoki 🔥 👍) — xato bermasdan reaksiya sifatida saqlanadi va preview yangilanadi.
  2) Havolali tugma kiritishda faqat bitta URL yuborilsa (masalan https://t.me/kanal)
     — avtomatik matn bilan tugma yasaladi:
       t.me → "📢 Kanalga o'tish", boshqa → "🔗 Batafsil"
  3) URL xavfsizligi (http/https/tg) saqlanadi.

Ishga tushirish:
    python3 tests/smart_emoji_and_url_test.py
    PYTHON=/tmp/venv/bin/python bash tests/run_tests.sh
"""
import asyncio
import os
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:SMART_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10005")
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

passed = 0
failures = 0

def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")

import handlers.manual_post as MP
import database as db_mod
from keyboards.inline import CB_MANUAL_URL_BTN, CB_MANUAL_REACT

USER_ID = 8888

class _Msg:
    def __init__(self, text=None, chat_id=USER_ID):
        self.text = text
        self.caption = None
        self.photo = None
        self.video = None
        self.document = None
        self.animation = None
        self.chat_id = chat_id
        self.message_id = 1
        self.from_user = SimpleNamespace(id=USER_ID, first_name="Tester")
        self.sent = []
    async def reply_text(self, text, **kwargs):
        self.sent.append(dict(kind="text", text=text, **kwargs))
        return SimpleNamespace(message_id=10)
    async def reply_photo(self, photo=None, **kwargs):
        self.sent.append(dict(kind="photo", photo=photo, **kwargs))
        return SimpleNamespace(message_id=11)
    async def reply_video(self, video=None, **kwargs):
        self.sent.append(dict(kind="video", video=video, **kwargs))
        return SimpleNamespace(message_id=12)
    async def reply_document(self, document=None, **kwargs):
        self.sent.append(dict(kind="document", document=document, **kwargs))
        return SimpleNamespace(message_id=13)
    async def reply_animation(self, animation=None, **kwargs):
        self.sent.append(dict(kind="animation", animation=animation, **kwargs))
        return SimpleNamespace(message_id=14)

class _Query:
    def __init__(self, data, message=None):
        self.data = data
        self.message = message or _Msg()
        self.from_user = SimpleNamespace(id=USER_ID, first_name="Tester")
        self.answered = []
        self.edits = []
    async def answer(self, text=None, **kwargs):
        self.answered.append(text)
        return True
    async def edit_message_text(self, text, **kwargs):
        self.edits.append(dict(text=text, **kwargs))
        return True
    async def edit_message_reply_markup(self, reply_markup=None):
        self.edits.append(dict(reply_markup=reply_markup))
        return True

def _update_msg(msg):
    return SimpleNamespace(message=msg, effective_message=msg,
                           effective_user=msg.from_user, callback_query=None)

def _update_query(query):
    return SimpleNamespace(message=None, effective_message=query.message,
                           effective_user=query.from_user, callback_query=query)

def _ctx(lang="uz", user_data=None):
    ud = {"lang": lang}
    ud.update(user_data or {})
    return SimpleNamespace(
        user_data=ud, chat_data={},
        bot=SimpleNamespace(username="postassist_test_bot"),
        application=None,
    )

def _run(coro):
    return asyncio.run(coro)

class _FakeDB:
    def __init__(self, values=None):
        self.values = values or {}
        self.calls = []
        self._orig = db_mod.run_db
        db_mod.run_db = self._fake
    async def _fake(self, fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        self.calls.append((name, kwargs))
        return self.values.get(name)
    def restore(self):
        db_mod.run_db = self._orig

def _start_flow(ctx, channels=(("-1001", "Kanal A"),)):
    fake = _FakeDB({"get_user_channels": list(channels), "add_post": 555})
    msg = _Msg(text="Test post matni")
    state = _run(MP.manual_post_entry(_update_msg(msg), ctx))
    if state != MP.MANUAL_AWAIT_CONTENT:
        fake.restore()
        return None, state, fake
    msg2 = _Msg(text="Test post matni")
    state2 = _run(MP.manual_content_received(_update_msg(msg2), ctx))
    return msg2, state2, fake

def test_smart_emoji_preview():
    print("\n== SMART EMOJI — preview holatida to'g'ridan-to'g'ri emoji ==")
    ctx = _ctx("uz")
    try:
        msg, state, fake = _start_flow(ctx)
        check("preview tayyor", state == MP.MANUAL_PREVIEW, str(state))
        # 😎
        m1 = _Msg(text="😎")
        s1 = _run(MP.manual_preview_emoji_received(_update_msg(m1), ctx))
        check("😎 qabul qilindi → PREVIEW", s1 == MP.MANUAL_PREVIEW, str(s1))
        check("😎 saqlandi", ctx.user_data.get(MP.UD_REACTIONS) == ["😎"], str(ctx.user_data.get(MP.UD_REACTIONS)))
        check("😎 preview yangilandi", m1.sent and "😎" in m1.sent[-1]["text"], str(m1.sent)[:200])
        # 🔥 👍
        m2 = _Msg(text="🔥 👍")
        s2 = _run(MP.manual_preview_emoji_received(_update_msg(m2), ctx))
        check("🔥 👍 qabul qilindi", s2 == MP.MANUAL_PREVIEW and ctx.user_data.get(MP.UD_REACTIONS) == ["🔥", "👍"], str(ctx.user_data.get(MP.UD_REACTIONS)))
        # max 5
        m3 = _Msg(text="😀 😃 😄 😁 😆 😅")  # 6
        s3 = _run(MP.manual_preview_emoji_received(_update_msg(m3), ctx))
        check("6 emoji → 5 tagacha", s3 == MP.MANUAL_PREVIEW and len(ctx.user_data.get(MP.UD_REACTIONS) or []) == 5, str(ctx.user_data.get(MP.UD_REACTIONS)))
    finally:
        fake.restore()

def test_smart_emoji_custom():
    print("\n== SMART EMOJI — custom holatida (O'zim kiritaman) ==")
    ctx = _ctx("uz")
    try:
        msg, state, fake = _start_flow(ctx)
        q = _Query(CB_MANUAL_REACT, msg)
        _run(MP.manual_panel_callback(_update_query(q), ctx))
        q2 = _Query(CB_MANUAL_REACT, msg)  # need to open custom? Actually we need custom
        # Open custom
        qc = _Query("mnp_radd", msg)
        stc = _run(MP.manual_panel_callback(_update_query(qc), ctx))
        check("custom holat ochildi (455)", stc == MP.MANUAL_REACTION_CUSTOM, str(stc))
        m1 = _Msg(text="😎")
        s1 = _run(MP.manual_reaction_custom_received(_update_msg(m1), ctx))
        check("custom'da 😎 → PREVIEW", s1 == MP.MANUAL_PREVIEW and ctx.user_data.get(MP.UD_REACTIONS) == ["😎"], str(ctx.user_data.get(MP.UD_REACTIONS)))
        m2 = _Msg(text="🔥 👍")
        # Need to reopen custom for second test
        _run(MP.manual_panel_callback(_update_query(_Query("mnp_radd", msg)), ctx))
        s2 = _run(MP.manual_reaction_custom_received(_update_msg(m2), ctx))
        check("custom'da 🔥 👍 → 2 ta", s2 == MP.MANUAL_PREVIEW and ctx.user_data.get(MP.UD_REACTIONS) == ["🔥", "👍"], str(ctx.user_data.get(MP.UD_REACTIONS)))
    finally:
        fake.restore()

def test_smart_url_single():
    print("\n== SMART URL — yakka URL avtomatik tugma ==")
    ctx = _ctx("uz")
    try:
        msg, state, fake = _start_flow(ctx)
        _run(MP.manual_panel_callback(_update_query(_Query(CB_MANUAL_URL_BTN, msg)), ctx))
        # t.me
        m1 = _Msg(text="https://t.me/kanal")
        s1 = _run(MP.manual_url_received(_update_msg(m1), ctx))
        check("https://t.me/kanal qabul qilindi", s1 == MP.MANUAL_PREVIEW, str(s1))
        check("t.me uchun matn '📢 Kanalga o'tish'", ctx.user_data.get(MP.UD_URL_BTN_TEXT) == "📢 Kanalga o'tish", str(ctx.user_data.get(MP.UD_URL_BTN_TEXT)))
        check("t.me URL saqlandi", ctx.user_data.get(MP.UD_URL_BTN_URL) == "https://t.me/kanal", str(ctx.user_data.get(MP.UD_URL_BTN_URL)))
        check("preview'da haqiqiy URL tugma", m1.sent and any(getattr(b, 'url', None) == "https://t.me/kanal" for row in m1.sent[-1]["reply_markup"].inline_keyboard for b in row), "no url btn")

        # other site
        ctx2 = _ctx("uz")
        msg2, state2, fake2 = _start_flow(ctx2)
        _run(MP.manual_panel_callback(_update_query(_Query(CB_MANUAL_URL_BTN, msg2)), ctx2))
        m2 = _Msg(text="https://sayt.uz")
        s2 = _run(MP.manual_url_received(_update_msg(m2), ctx2))
        check("https://sayt.uz qabul qilindi", s2 == MP.MANUAL_PREVIEW, str(s2))
        check("sayt.uz uchun matn '🔗 Batafsil'", ctx2.user_data.get(MP.UD_URL_BTN_TEXT) == "🔗 Batafsil", str(ctx2.user_data.get(MP.UD_URL_BTN_TEXT)))
        fake2.restore()
    finally:
        try:
            fake.restore()
        except:
            pass

def test_smart_url_with_text():
    print("\n== SMART URL — Matn - Havola formati saqlanadi ==")
    ctx = _ctx("uz")
    try:
        msg, state, fake = _start_flow(ctx)
        _run(MP.manual_panel_callback(_update_query(_Query(CB_MANUAL_URL_BTN, msg)), ctx))
        m1 = _Msg(text="Kanalga o'tish - https://t.me/kanal")
        s1 = _run(MP.manual_url_received(_update_msg(m1), ctx))
        check("Matn - URL formati qabul qilindi", s1 == MP.MANUAL_PREVIEW and ctx.user_data.get(MP.UD_URL_BTN_TEXT) == "Kanalga o'tish", str(ctx.user_data.get(MP.UD_URL_BTN_TEXT)))
        check("URL saqlandi", ctx.user_data.get(MP.UD_URL_BTN_URL) == "https://t.me/kanal", str(ctx.user_data.get(MP.UD_URL_BTN_URL)))
    finally:
        fake.restore()

def test_url_security():
    print("\n== URL XAVFSIZLIGI — faqat http/https/tg ==")
    ctx = _ctx("uz")
    try:
        msg, state, fake = _start_flow(ctx)
        _run(MP.manual_panel_callback(_update_query(_Query(CB_MANUAL_URL_BTN, msg)), ctx))
        for bad in ["javascript:alert(1)", "file:///etc/passwd", "data:text/html;base64,xxx", "ftp://example.com"]:
            m = _Msg(text=bad)
            s = _run(MP.manual_url_received(_update_msg(m), ctx))
            check(f"xavfli {bad[:20]} rad etildi", s == MP.MANUAL_URL_INPUT and not ctx.user_data.get(MP.UD_URL_BTN_URL), str(s))
            # clear
            ctx.user_data.pop(MP.UD_URL_BTN_URL, None)
            ctx.user_data.pop(MP.UD_URL_BTN_TEXT, None)
    finally:
        fake.restore()

def main():
    print("="*70)
    print(" SMART EMOJI VA SMART URL PARSER — 2-QISM BUGFIX TESTI")
    print("="*70)
    test_smart_emoji_preview()
    test_smart_emoji_custom()
    test_smart_url_single()
    test_smart_url_with_text()
    test_url_security()
    print("\n"+"="*70)
    print(f" JAMI: o'tdi={passed}, xato={failures}")
    if failures == 0:
        print(" SMART EMOJI VA URL TESTLARI 100% YASHIL ✔")
    print("="*70)
    return failures == 0

if __name__ == "__main__":
    sys.exit(0 if main() else 1)
