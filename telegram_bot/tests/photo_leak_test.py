#!/usr/bin/env python3
"""📸 RASM SPAMINI TUZATISH + 🎙 KANAL OVOZI regression testlari.

Qamrab olinadigan xatolar/va'da:
  1. Yangi post oqimida (har qanday bosqich) yuborilgan rasm/albom hech qachon
     adminga bormaydi va foydalanuvchiga "📸 Rasmingiz adminga yuborildi..."
     xabari chiqmaydi — rasm JIM yutiladi.
  2. Rasm adminga FAQAT ikkita ANIQ holatda boradi:
       - "Moderatsiya" (PHOTO_CHECK_WAIT) dialog holati/`photo_check_wait`
         user_data belgisi,
       - to'lov cheki oqimi (RECEIPT_WAIT) — faqat bitta chek (albom ikkinchi
         rasmi ikkinchi chek bo'lib o'tmaydi).
  3. To'lov cheki adminga FAQAT RECEIPT_WAIT holatida yuboriladi (boshqa
     dialogda yuborilgan rasm/PDF chek sifatida o'tmaydi).
  4. 🎙 "Kanal ovozi" tugmasi kanal profilida bor va AI tahlil natijasi
     kanalning tone_of_voice maydoniga saqlanadi.

Ishga tushirish:
    cd telegram_bot && python tests/photo_leak_test.py
"""
import asyncio
import os
import sys
import warnings
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from telegram import Update, Message, Chat, User, PhotoSize, Bot  # noqa: E402
from telegram.ext import ApplicationBuilder, ConversationHandler, CallbackContext  # noqa: E402

from handlers import register_all_handlers  # noqa: E402
import handlers.new_post as np_mod  # noqa: E402
from handlers.new_post import (  # noqa: E402
    CHOOSE_CHANNEL, GET_CONTENT, GET_BTN_TITLE, GET_BTN_URL, GET_REACTIONS,
    GET_AUTO_DELETE, GET_TIME, DAILY_TIME, RECUR_DAY, RECUR_TIME,
    GET_DURATION,
)
from handlers.photo_check import PHOTO_CHECK_WAIT, UD_PHOTO_CHECK_WAIT, handle_user_photo
from handlers.subscription import RECEIPT_WAIT  # noqa: E402
from keyboards.inline import render_channels_list  # noqa: E402
from locales.translations import get_text  # noqa: E402

CHECKS = []


def check(msg, cond, detail=""):
    CHECKS.append((bool(cond), msg, detail))
    if not cond:
        print(f"  [FAIL] {msg}: {detail}")
    else:
        print(f"  [OK] {msg}")


# ----------------------------------------------------------------------
# Infratuzilma
# ----------------------------------------------------------------------
class _RecBot:
    """send_message / send_photo / send_document chaqiruvlarini yozadi."""
    id = 1
    username = "TestBot"
    defaults = None

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id=None, text=None, reply_markup=None,
                           parse_mode=None, **kw):
        self.sent.append({"kind": "message", "chat_id": chat_id, "text": text,
                          "reply_markup": reply_markup})
        return SimpleNamespace(message_id=len(self.sent))

    async def send_photo(self, chat_id=None, photo=None, caption=None,
                         reply_markup=None, parse_mode=None, **kw):
        self.sent.append({"kind": "admin_photo", "chat_id": chat_id,
                          "photo": photo, "caption": caption or "",
                          "reply_markup": reply_markup})
        return SimpleNamespace(message_id=len(self.sent))

    async def send_document(self, chat_id=None, document=None, caption=None,
                            reply_markup=None, parse_mode=None, **kw):
        self.sent.append({"kind": "admin_doc", "chat_id": chat_id,
                          "document": document, "caption": caption or "",
                          "reply_markup": reply_markup})
        return SimpleNamespace(message_id=len(self.sent))


def _text_update(uid, text, bot=None):
    user = User(id=uid, first_name="Ali", is_bot=False)
    chat = Chat(id=uid, type="private")
    msg = Message(message_id=1, date=datetime.now(), chat=chat, from_user=user, text=text)
    if bot is not None:
        msg.set_bot(bot)
    upd = Update(update_id=1, message=msg)
    if bot is not None:
        upd.set_bot(bot)
    return upd


def _photo_update(uid, file_id, caption="", media_group_id=None, bot=None,
                  message_id=1):
    user = User(id=uid, first_name="Ali", is_bot=False)
    chat = Chat(id=uid, type="private")
    kw = dict(message_id=message_id, date=datetime.now(), chat=chat,
              from_user=user)
    if file_id:
        kw["photo"] = [PhotoSize(file_id=file_id, file_unique_id=file_id + "_u",
                                 width=320, height=240)]
    if caption:
        kw["caption"] = caption
    if media_group_id:
        kw["media_group_id"] = media_group_id
    msg = Message(**kw)
    if bot is not None:
        msg.set_bot(bot)
    upd = Update(update_id=1, message=msg)
    if bot is not None:
        upd.set_bot(bot)
    return upd


def _callback_update(uid, data, bot=None):
    """Inline tugma bosilishi (callback_query) uchun minimal Update."""
    user = User(id=uid, first_name="Ali", is_bot=False)
    chat = Chat(id=uid, type="private")
    msg = Message(message_id=1, date=datetime.now(), chat=chat, from_user=user,
                  text="x")
    if bot is not None:
        msg.set_bot(bot)

    class _Msg:
        def __init__(self, real):
            self.real = real
            self.replies = []
            self.chat_id = uid

        async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
            self.replies.append(text)
            if bot is not None:
                bot.sent.append({"kind": "message", "chat_id": self.chat_id,
                                 "text": text, "reply_markup": reply_markup})
            return SimpleNamespace(message_id=1)

        async def delete(self, **kw):
            return True

        def __getattr__(self, item):
            return getattr(self.real, item)

    msgw = _Msg(msg)

    class _Query:
        def __init__(self):
            self.data = data
            self.from_user = user
            self.message = msgw
            self.answers = []
            self.edits = []

        async def answer(self, text=None, show_alert=False):
            self.answers.append((text, show_alert))

        async def edit_message_text(self, text, reply_markup=None,
                                    parse_mode=None, **kw):
            self.edits.append((text, reply_markup))
            return True

    query = _Query()
    upd = Update(update_id=2, callback_query=query)
    if bot is not None:
        upd.set_bot(bot)
    return upd


def _build_app():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = ApplicationBuilder().token("123456:TEST_TOKEN").build()
        register_all_handlers(app)
    return app


def _get_main_conv(app):
    return [h for h in app.handlers[0] if isinstance(h, ConversationHandler)][0]


def _seed_state(app, uid, state):
    conv = _get_main_conv(app)
    if state is None:
        conv._conversations.pop((uid, uid), None)
    else:
        conv._conversations[(uid, uid)] = state
    return conv


def _first_matching_handler(app, upd):
    for group in sorted(app.handlers):
        for handler in app.handlers[group]:
            check_ = handler.check_update(upd)
            if check_ is None or check_ is False:
                continue
            return group, handler, check_
    return None


async def _dispatch(app, upd, lang="uz", user_data=None):
    found = _first_matching_handler(app, upd)
    if not found:
        return None
    group, handler, check = found
    ctx = CallbackContext(app, chat_id=upd.effective_chat.id,
                          user_id=upd.effective_user.id)
    ctx.user_data["lang"] = lang
    if user_data is not None:
        ctx.user_data.update(user_data)
    await handler.handle_update(upd, app, check, ctx)
    return handler


# Handlerlar ichidagi ``context.bot`` (ExtBot) real tarmoqqa chiqmasligi
# uchun telegram.Bot klassining yuborish metodlari bir marta almashtiriladi;
# qaysi test bo'lsa, natijalar shu testning sink'iga yoziladi.
_ACTIVE_SINK = []


def _patch_app_bot(app, sink):
    """``context.bot`` (ExtBot) tarmoqqa chiqmasligi uchun Bot klassining
    asosiy yuborish metodlarini recorder'ga almashtiramiz.

    ``CallbackContext.bot`` — o'qish uchun property (Application'dagi ExtBot),
    shuning uchun klass darajasida almashtirish eng xavfsiz yo'l: hech qachon
    real HTTP/TLS so'rov ketmaydi, barcha chiqishlar sink'ga yoziladi.
    """
    global _ACTIVE_SINK
    _ACTIVE_SINK = sink
    if getattr(Bot, "_photo_leak_methods_patched", False):
        return
    from telegram import Bot as _Bot

    async def _send_message(self, chat_id=None, text=None, reply_markup=None,
                            parse_mode=None, **kw):
        if _ACTIVE_SINK is not None:
            _ACTIVE_SINK.append({"kind": "message", "chat_id": chat_id,
                                 "text": text, "reply_markup": reply_markup})
        return SimpleNamespace(message_id=1)

    async def _send_photo(self, chat_id=None, photo=None, caption=None,
                          reply_markup=None, parse_mode=None, **kw):
        if _ACTIVE_SINK is not None:
            _ACTIVE_SINK.append({"kind": "admin_photo", "chat_id": chat_id,
                                 "photo": photo, "caption": caption or "",
                                 "reply_markup": reply_markup})
        return SimpleNamespace(message_id=1)

    async def _send_document(self, chat_id=None, document=None, caption=None,
                             reply_markup=None, parse_mode=None, **kw):
        if _ACTIVE_SINK is not None:
            _ACTIVE_SINK.append({"kind": "admin_doc", "chat_id": chat_id,
                                 "document": document, "caption": caption or "",
                                 "reply_markup": reply_markup})
        return SimpleNamespace(message_id=1)

    _Bot.send_message = _send_message
    _Bot.send_photo = _send_photo
    _Bot.send_document = _send_document
    _Bot._photo_leak_methods_patched = True


def _patch_db(responses=None):
    import database as db_mod
    responses = responses or {}

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        if name in responses:
            val = responses[name]
            return val(*args, **kwargs) if callable(val) else val
        raise AssertionError(f"kutilmagan db chaqiruvi: {name}")

    orig = db_mod.run_db
    db_mod.run_db = fake_run_db
    return lambda: setattr(db_mod, "run_db", orig)


def _admin_photos(bot):
    return [s for s in bot.sent if s["kind"] in ("admin_photo", "admin_doc")]


def _spam_replies(bot):
    return [s for s in bot.sent if s["kind"] == "message"
            and ("adminga yuborildi" in (s.get("text") or "")
                 or "отправлено администратору" in (s.get("text") or ""))]


# ----------------------------------------------------------------------
# 1. PHOTO_CHECK gate: moderatsiya holatida bo'lmagan rasm — JIM yutiladi
# ----------------------------------------------------------------------
def test_outside_moderation_photo_is_silent():
    print("== 1. Moderatsiyadan tashqari rasm JIM yutiladi ==")
    bot = _RecBot()
    upd = _photo_update(42, "leak1", bot=bot)
    ctx = SimpleNamespace(application=None, bot=bot, user_data={})

    async def run():
        return await handle_user_photo(upd, ctx)

    state = asyncio.run(run())
    check("tashqari: holat/END qaytmaydi", state is None, str(state))
    check("tashqari: adminga rasm yuborilmadi", not _admin_photos(bot))
    check("tashqari: 'yuborildi' xabari chiqmadi", not _spam_replies(bot))


def test_outside_moderation_photo_in_newpost_states_silent():
    print("== 1b. Yangi post holatlari + rasm → adminga hech narsa bormaydi ==")
    # CONFIRM_POST/EDIT_CONFIRM_FIELD bu yerda EMAS: ular media'ni ATABAY
    # qabul qiladi (edit_confirm_* handlerlari) — boshqa xavfsiz yo'l. Matn
    # kutayotgan quyidagi holatlarda rasm ConversationHandler'ga mos kelmaydi
    # va global photo handler'ga tushadi — aynan shu yo'l spamlangan edi.
    states = (
        CHOOSE_CHANNEL, GET_BTN_TITLE, GET_BTN_URL, GET_REACTIONS,
        GET_AUTO_DELETE, GET_TIME, DAILY_TIME, RECUR_DAY, RECUR_TIME,
        GET_DURATION,
    )
    restore = _patch_db({"get_user_language": "uz"})
    try:
        for i, state in enumerate(states):
            app = _build_app()
            conv = _seed_state(app, 42, state)
            bot = _RecBot()
            _patch_app_bot(app, bot.sent)
            upd = _photo_update(42, f"np{i}", caption="", bot=bot,
                                message_id=100 + i)
            asyncio.run(_dispatch(app, upd, lang="uz"))
            ok = (not _admin_photos(bot)) and (not _spam_replies(bot))
            check(f"{state}: rasm adminga bormadi va xabar chiqmadi", ok,
                  str(bot.sent)[:200])
            conv._conversations.pop((42, 42), None)
    finally:
        restore()


def test_newpost_album_photos_do_not_leak_to_admin():
    print("== 1c. Yangi post (GET_CONTENT) albom rasmlari adminga bormaydi ==")
    np_mod._ALBUM_BUFFERS.clear()
    old_wait = np_mod._ALBUM_WAIT_SECONDS
    np_mod._ALBUM_WAIT_SECONDS = 0.1
    app = _build_app()
    conv = _seed_state(app, 42, GET_CONTENT)
    restore = _patch_db({"get_user_language": "uz"})
    bot = _RecBot()
    _patch_app_bot(app, bot.sent)
    try:
        async def run():
            for i, fid in enumerate(("a1", "a2", "a3")):
                upd = _photo_update(42, fid, caption="Albom izohi" if i == 0 else "",
                                    media_group_id="leakg", bot=bot,
                                    message_id=200 + i)
                await _dispatch(app, upd, lang="uz")
            await asyncio.sleep(np_mod._ALBUM_WAIT_SECONDS + 0.4)

        asyncio.run(run())
    finally:
        np_mod._ALBUM_WAIT_SECONDS = old_wait
        np_mod._ALBUM_BUFFERS.clear()
        conv._conversations.pop((42, 42), None)
        restore()

    check("albom: adminga rasm bormadi", not _admin_photos(bot),
          str(bot.sent)[:200])
    check("albom: 'yuborildi' spami chiqmadi", not _spam_replies(bot))
    check("albom: oqim so'rovi davom etdi (tugma izohi)",
          any("tugma" in (s.get("text") or "") for s in bot.sent),
          str(bot.sent)[:300])


# ----------------------------------------------------------------------
# 2. PHOTO_CHECK gate: moderatsiya holatida rasm adminga BORADI
# ----------------------------------------------------------------------
def test_moderation_marker_photo_goes_to_admin():
    print("== 2. 'photo_check_wait' belgisi bilan rasm adminga boradi ==")
    bot = _RecBot()
    upd = _photo_update(42, "ok1", bot=bot)
    ctx = SimpleNamespace(application=None, bot=bot,
                          user_data={UD_PHOTO_CHECK_WAIT: True})

    async def run():
        return await handle_user_photo(upd, ctx)

    state = asyncio.run(run())
    check("moderatsiya: rasm adminga yuborildi", len(_admin_photos(bot)) == 1,
          str(bot.sent))
    check("moderatsiya: admin tasdiqlash tugmalari bor", bool(
        _admin_photos(bot) and _admin_photos(bot)[0]["reply_markup"]))
    check("moderatsiya: foydalanuvchiga tasdiq xabari",
          any("Tasdiqlanishi kutilmoqda" in s.get("text") or ""
              for s in bot.sent if s["kind"] == "message"))
    check("moderatsiya: bir martalik marker tozalandi",
          UD_PHOTO_CHECK_WAIT not in ctx.user_data)
    check("moderatsiya: END qaytadi", state == ConversationHandler.END,
          str(state))


def test_moderation_state_photo_goes_to_admin_via_conv():
    print("== 2b. PHOTO_CHECK_WAIT holatida rasm adminga boradi ==")
    app = _build_app()
    conv = _seed_state(app, 42, PHOTO_CHECK_WAIT)
    restore = _patch_db({"get_user_language": "uz"})
    bot = _RecBot()
    _patch_app_bot(app, bot.sent)
    try:
        upd = _photo_update(42, "ok2", caption="", bot=bot, message_id=300)
        handler = asyncio.run(_dispatch(app, upd, lang="uz"))
        ok = isinstance(handler, ConversationHandler)
        check("2b: rasmni ConversationHandler ushladi", ok, str(handler))
        check("2b: adminga yuborildi", len(_admin_photos(bot)) == 1,
              str(bot.sent)[:200])
    finally:
        conv._conversations.pop((42, 42), None)
        restore()


# ----------------------------------------------------------------------
# 3. To'lov cheki (RECEIPT_WAIT) gate
# ----------------------------------------------------------------------
def test_receipt_only_in_receipt_wait_state():
    print("== 3. Chek faqat RECEIPT_WAIT holatida qabul qilinadi ==")
    app = _build_app()
    conv = _get_main_conv(app)
    restore = _patch_db({
        "save_payment_receipt": 55,
        "get_user_language": "uz",
    })
    try:
        # 3a) Yangi post oqimida (GET_TIME) yuborilgan rasm — chek EMAS
        _seed_state(app, 42, GET_TIME)
        bot = _RecBot()
        _patch_app_bot(app, bot.sent)
        upd = _photo_update(42, "not_receipt", caption="", bot=bot,
                            message_id=400)
        asyncio.run(_dispatch(app, upd, lang="uz"))
        check("3a: chek adminga bormadi", not _admin_photos(bot),
              str(bot.sent)[:200])
        check("3a: post oqimi buzilmadi (GET_TIME holatida qoldi)",
              conv._conversations.get((42, 42)) == GET_TIME,
              str(conv._conversations.get((42, 42))))

        # 3b) RECEIPT_WAIT holatida rasm — chek sifatida qabul qilinadi
        _seed_state(app, 42, RECEIPT_WAIT)
        bot2 = _RecBot()
        _patch_app_bot(app, bot2.sent)
        upd2 = _photo_update(42, "real_receipt", caption="Chek izohi",
                             bot=bot2, message_id=401)
        handler2 = asyncio.run(_dispatch(app, upd2, lang="uz"))
        check("3b: chek qabul qilindi (conversation ushladi)",
              isinstance(handler2, ConversationHandler), str(handler2))
        check("3b: adminga chek yuborildi",
              len(_admin_photos(bot2)) == 1, str(bot2.sent)[:300])
        check("3b: foydalanuvchiga tasdiq xabari",
              any("qabul qilindi" in (s.get("text") or "")
                  for s in bot2.sent if s["kind"] == "message"))
        check("3b: dialog tugadi (END)",
              (42, 42) not in conv._conversations,
              str(conv._conversations.get((42, 42))))
    finally:
        conv._conversations.pop((42, 42), None)
        restore()


def test_receipt_album_only_first_photo_counted():
    print("== 3c. Chek sifatida yuborilgan ALBOM — faqat bitta chek ==")
    app = _build_app()
    conv = _get_main_conv(app)
    saves = []
    restore = _patch_db({
        "save_payment_receipt": lambda *a, **k: saves.append(a) or 55,
        "get_user_language": "uz",
    })
    bot = _RecBot()
    _patch_app_bot(app, bot.sent)
    try:
        _seed_state(app, 42, RECEIPT_WAIT)
        upd1 = _photo_update(42, "rec1", caption="Chek", media_group_id="rg1",
                             bot=bot, message_id=500)
        asyncio.run(_dispatch(app, upd1, lang="uz"))
        check("3c: birinchi rasm chek bo'ldi", len(_admin_photos(bot)) == 1,
              str(bot.sent)[:300])
        check("3c: DB'ga bitta chek yozildi", len(saves) == 1, str(saves))

        # Ikkinchi albom rasmi — dialog END bo'lgan, chek o'tmaydi
        upd2 = _photo_update(42, "rec2", caption="", media_group_id="rg1",
                             bot=bot, message_id=501)
        asyncio.run(_dispatch(app, upd2, lang="uz"))
        check("3c: ikkinchi rasm chek bo'lmadi",
              len(_admin_photos(bot)) == 1, str(bot.sent)[:300])
        check("3c: DB'ga ikkinchi yozuv yo'q", len(saves) == 1, str(saves))
    finally:
        conv._conversations.pop((42, 42), None)
        restore()


# ----------------------------------------------------------------------
# 4. Kanal ovozi: tugma + AI tahlil → tone_of_voice ga saqlash
# ----------------------------------------------------------------------
def test_channels_list_has_voice_button():
    print("== 4. Kanal profilida 'Kanal ovozi' tugmasi ==")
    for lang in ("uz", "ru"):
        kb = render_channels_list([("-1001234567890", "Mening Kanalim",
                                    "friendly")], lang)
        cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
        label = get_text("ch_voice_btn", lang)
        texts = [b.text for row in kb.inline_keyboard for b in row]
        check(f"4[{lang}]: ch_voice tugmasi bor", "ch_voice:-1001234567890" in cbs,
              str(cbs))
        check(f"4[{lang}]: ch_voice yorlig'i", any(label in t for t in texts),
              str(texts)[:200])


def test_channel_voice_analysis_saves_tone():
    print("== 4b. AI tahlil natijasi tone_of_voice ga saqlanadi ==")
    import handlers.channels as ch_mod
    app = _build_app()
    db_calls = []
    orig_analyze = ch_mod.analyze_channel_voice

    async def fake_analyze(posts, lang="uz"):
        return {"tone": "formal", "reason": "Postlarda rasmiy murojaat uslubi."}

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        db_calls.append((name, args))
        if name == "get_user_channels_with_tone":
            return [("-1001234567890", "Mening Kanalim", "friendly")]
        if name == "get_channel_posts_history":
            return [{"text": "Assalomu alaykum! Yangi mahsulot yetib keldi."}]
        if name == "set_channel_tone":
            return True
        raise AssertionError(f"kutilmagan db chaqiruvi: {name}")

    import database as db_mod
    orig_run_db = db_mod.run_db
    db_mod.run_db = fake_run_db
    ch_mod.analyze_channel_voice = fake_analyze
    bot = _RecBot()
    try:
        upd = _callback_update(42, "ch_voice:-1001234567890", bot=bot)
        state = asyncio.run(ch_mod.channel_voice_analysis_callback(upd, SimpleNamespace(
            application=app, bot=bot, user_data={"lang": "uz"})))
        check("4b: handler END qaytardi", state == ConversationHandler.END,
              str(state))
        sets = [a for name, a in db_calls if name == "set_channel_tone"]
        check("4b: tone_of_voice saqlandi (formal)",
              sets == [("-1001234567890", "formal")], str(sets))
        replies = [s for s in bot.sent if s["kind"] == "message"]
        check("4b: natija xabari chiqdi",
              any("Kanal ovozi tahlili natijasi" in (r.get("text") or "")
                  for r in replies), str(replies)[:200])
    finally:
        db_mod.run_db = orig_run_db
        ch_mod.analyze_channel_voice = orig_analyze


def test_channel_voice_requires_own_channel_and_tone():
    print("== 4c. Boshqa kanal/yo'q natija → xato, DB'ga yozilmaydi ==")
    import handlers.channels as ch_mod
    import database as db_mod
    db_calls = []
    orig_analyze = ch_mod.analyze_channel_voice

    async def fake_analyze(posts, lang="uz"):
        return {"error": "Tahlil uchun postlar yetarli emas"}

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        db_calls.append((name, args))
        if name == "get_user_channels_with_tone":
            return [("-1001234567890", "Mening Kanalim", "friendly")]
        if name == "get_channel_posts_history":
            return [{"text": "E'lon: yangi chegirma"}]
        raise AssertionError(f"kutilmagan db chaqiruvi: {name}")

    orig_run_db = db_mod.run_db
    db_mod.run_db = fake_run_db
    ch_mod.analyze_channel_voice = fake_analyze
    try:
        # 4c-1) Boshqa foydalanuvchining kanali → ruxsat yo'q, saqlanmaydi
        bot = _RecBot()
        upd = _callback_update(42, "ch_voice:-999999999999", bot=bot)
        asyncio.run(ch_mod.channel_voice_analysis_callback(upd, SimpleNamespace(
            application=None, bot=bot, user_data={"lang": "uz"})))
        check("4c-1: notanish kanal → saqlanmadi",
              not any(a[0] == "set_channel_tone" for a in db_calls),
              str(db_calls))
        # 4c-2) AI natijasida tone yo'q → xato xabari, saqlanmaydi
        db_calls.clear()
        bot2 = _RecBot()
        upd2 = _callback_update(42, "ch_voice:-1001234567890", bot=bot2)
        asyncio.run(ch_mod.channel_voice_analysis_callback(upd2, SimpleNamespace(
            application=None, bot=bot2, user_data={"lang": "uz"})))
        check("4c-2: tone yo'q → xato xabari",
              any("yetarli" in (s.get("text") or "") or "error" in
                  ((s.get("text") or "").lower()) for s in bot2.sent
                  if s["kind"] == "message"), str(bot2.sent)[:200])
        check("4c-2: tone yo'q → saqlanmadi",
              not any(a[0] == "set_channel_tone" for a in db_calls),
              str(db_calls))
    finally:
        db_mod.run_db = orig_run_db
        ch_mod.analyze_channel_voice = orig_analyze


# ======================================================================
if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
    failed = [c for c in CHECKS if not c[0]]
    print(f"\nPhoto-leak/voice testlari: {len(CHECKS) - len(failed)} passed, "
          f"{len(failed)} failed")
    if failed:
        for _, msg, detail in failed:
            print(f"  [FAIL] {msg} {detail}")
        sys.exit(1)
    print("BARCHASI OK ✔")
