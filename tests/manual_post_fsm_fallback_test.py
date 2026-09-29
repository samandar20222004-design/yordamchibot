#!/usr/bin/env python3
"""💡 FSM INPUT FALLBACK — MANUAL POST BOSQICHLARIDA YUMSHOQ JAVOB (PHASE 1).

Muammo: foydalanuvchi «Post preview» yoki sozlash bosqichida (kanal tanlash,
reaksiya kiritish, havolali tugma) turganda tugma bosish o'rniga adashib
erkin matn yozsa yoki media tashlasa — bot quruq «Bu turdagi xabar qabul
qilinmaydi» (unknown_in_dialog) bilan javob berib, joriy menyuni
ko'rsatmasdan qolib ketardi.

Yechim (handlers/manual_post.py + handlers/__init__.py):
  * MANUAL_PREVIEW + erkin matn (emoji'siz) / media → 💡 yumshoq eslatma
    («Hozirgi bosqichda quyidagi tugmalardan birini tanlashingiz kerak:»)
    + mavjud Preview menyusi qayta ko'rsatiladi, FSM holati SAQLANADI;
  * MANUAL_CHANNEL_SELECT + matn/media → 💡 + kanal tanlov klaviaturasi;
  * MANUAL_REACTION_CUSTOM + media → 💡 + kiritish yo'riqnomasi;
  * MANUAL_URL_INPUT + media → 💡 + kiritish yo'riqnomasi;
  * SMART EMOJI va eski aniq xato xabarlari (mp_url_invalid,
    mp_react_custom_invalid, mp_time_invalid) O'ZGARMAYDI (regressiya).

Ishga tushirish:
    PYTHON=/tmp/venv/bin/python bash tests/run_tests.sh   # runner bosqichi
    python3 tests/manual_post_fsm_fallback_test.py
"""
import asyncio
import os
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

# ------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanadi.
# ------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:FSM_FALLBACK_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10043")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

passed = 0
failures = 0
LANGS = ("uz", "ru", "en")


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


from telegram.ext import ConversationHandler, MessageHandler  # noqa: E402

import handlers as H  # noqa: E402
import handlers.manual_post as MP  # noqa: E402
import database as db_mod  # noqa: E402
from keyboards.inline import (  # noqa: E402
    CB_MANUAL_NOW, CB_MANUAL_REACT_CUSTOM, CB_MANUAL_URL_BTN,
    manual_channel_callback,
)
from translations import manual_post_t  # noqa: E402

USER_ID = 7777


# ------------------------------------------------------------------
# YORDAMCHILAR — yengil Update/Context/DB fakeri (tarmoqqa chiqmaydi)
# ------------------------------------------------------------------
class _Msg:
    """reply_text / reply_photo ... yozib boruvchi soxta xabar."""

    def __init__(self, text=None, photo=False):
        self.text = text
        self.caption = None
        self.photo = (SimpleNamespace(file_id="FID"),) if photo else None
        self.video = None
        self.document = None
        self.animation = None
        self.chat_id = USER_ID
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


def _update_msg(msg):
    return SimpleNamespace(message=msg, effective_message=msg,
                           effective_user=msg.from_user, callback_query=None)


def _update_query(query):
    return SimpleNamespace(message=None, effective_message=query.message,
                           effective_user=query.from_user,
                           callback_query=query)


class _Query:
    """Soxta callback query (answer/edit yozib boradi)."""

    def __init__(self, data, message=None):
        self.data = data
        self.message = message or _Msg()
        self.from_user = SimpleNamespace(id=USER_ID, first_name="Tester")

    async def answer(self, text=None, **kwargs):
        return True

    async def edit_message_text(self, text, **kwargs):
        return True

    async def edit_message_reply_markup(self, reply_markup=None):
        return True


def _ctx(lang="uz", user_data=None):
    ud = {"lang": lang}
    ud.update(user_data or {})
    return SimpleNamespace(user_data=ud, chat_data={},
                           bot=SimpleNamespace(username="postassist_test_bot"),
                           application=None)


class _FakeDB:
    """database.run_db'ni soxtalashtiradi va chaqiruvlarni yozib boradi."""

    def __init__(self, values=None):
        self.values = values or {}
        self.calls = []
        self._orig = db_mod.run_db
        db_mod.run_db = self._fake

    async def _fake(self, fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        self.calls.append((name, args))
        return self.values.get(name)

    def restore(self):
        db_mod.run_db = self._orig


def _run(coro):
    return asyncio.run(coro)


def _start_manual_flow(ctx, channels=(("-1001", "Kanal A"),)):
    """✍️ entry → kontent → PREVIEW. Qaytaradi: (preview msg, state, fake)."""
    fake = _FakeDB({"get_user_channels": list(channels), "add_post": 555})
    msg = _Msg(text="Yangi mahsulot: endi -30% chegirma!")
    state = _run(MP.manual_post_entry(_update_msg(msg), ctx))
    if state != MP.MANUAL_AWAIT_CONTENT:
        fake.restore()
        return None, state, fake
    msg2 = _Msg(text="Yangi mahsulot: endi -30% chegirma!")
    state2 = _run(MP.manual_content_received(_update_msg(msg2), ctx))
    return msg2, state2, fake


def _texts(msg):
    return [s.get("text") or "" for s in msg.sent]


def _cbs(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def _build_app():
    from telegram.ext import ApplicationBuilder
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = ApplicationBuilder().token("123456:FSM_FALLBACK_TEST").build()
    H.register_all_handlers(app)
    return app


def _main_conv(app):
    return [h for h in (h for g in sorted(app.handlers) for h in app.handlers[g])
            if isinstance(h, ConversationHandler)][0]


def _tg_update(text=None, photo=False, command=False):
    """Haqiqiy telegram.Update (filtr semantikasi tekshiruvi uchun)."""
    from telegram import Update
    message = {
        "message_id": 10, "date": 0,
        "chat": {"id": USER_ID, "type": "private"},
        "from": {"id": USER_ID, "is_bot": False, "first_name": "Tester"},
    }
    if text is not None:
        message["text"] = text
    if command:
        # Real Telegram buyruqlarida bot_command entity bo'ladi (PTB
        # filters.COMMAND aynan shunga qaraydi).
        message["entities"] = [{"offset": 0, "length": len(text or "/start"),
                                "type": "bot_command"}]
    if photo:
        message["photo"] = [{"file_id": "FID", "file_unique_id": "FUID",
                             "width": 8, "height": 8}]
    return Update.de_json({"update_id": 1, "message": message}, None)


# ============================================================================
# TEST 1 — PREVIEW + erkin matn: 💡 eslatma + preview qayta + HOLAT SAQLANADI
# ============================================================================
def test_preview_free_text():
    print("\n== TEST 1: preview'da erkin matn — 💡 eslatma + menyuni qayta ==")
    for lang in LANGS:
        ctx = _ctx(lang)
        try:
            _msg, state, fake = _start_manual_flow(ctx)
            check(f"[{lang}] preview tayyor", state == MP.MANUAL_PREVIEW,
                  str(state))
            free = _Msg(text="salom, bu erkin matn (tugma bosish kerak edi)")
            st = _run(MP.manual_preview_emoji_received(_update_msg(free), ctx))
            hint = manual_post_t("mp_stage_hint", lang)
            check(f"[{lang}] holat SAQLANDI (MANUAL_PREVIEW)",
                  st == MP.MANUAL_PREVIEW, str(st))
            check(f"[{lang}] 💡 yumshoq eslatma yuborildi",
                  hint in _texts(free), str(_texts(free))[:160])
            check(f"[{lang}] eslatma — BIRINCHI xabar",
                  free.sent and _texts(free)[0] == hint, str(_texts(free))[:160])
            check(f"[{lang}] Preview menyusi qayta ko'rsatildi",
                  len(free.sent) >= 2
                  and manual_post_t("mp_preview_title", lang)
                  in (_texts(free)[-1] or ""), str(_texts(free)[-1])[:80])
            check(f"[{lang}] preview paneli (mnp_ tugmalari) qaytdi",
                  free.sent[-1].get("reply_markup") is not None
                  and any(cb.startswith("mnp_")
                          for cb in _cbs(free.sent[-1]["reply_markup"])), "")
            check(f"[{lang}] kontent yo'qolmadi",
                  ctx.user_data.get(MP.UD_CONTENT)
                  == "Yangi mahsulot: endi -30% chegirma!", "")
        finally:
            fake.restore()


# ============================================================================
# TEST 2 — PREVIEW + MEDIA: 💡 eslatma + preview qayta + holat saqlanadi
# ============================================================================
def test_preview_media():
    print("\n== TEST 2: preview'da MEDIA (rasm) — yumshoq fallback ==")
    for lang in LANGS:
        ctx = _ctx(lang)
        try:
            _msg, _state, fake = _start_manual_flow(ctx)
            media = _Msg(photo=True)
            st = _run(MP.manual_preview_media_received(_update_msg(media), ctx))
            hint = manual_post_t("mp_stage_hint", lang)
            check(f"[{lang}] media → MANUAL_PREVIEW saqlanadi",
                  st == MP.MANUAL_PREVIEW, str(st))
            check(f"[{lang}] media → 💡 eslatma + preview qayta",
                  hint in _texts(media) and len(media.sent) >= 2,
                  str(_texts(media))[:160])
        finally:
            fake.restore()

    # Sessiya eskirgan (kontent yo'q) — eski xulq saqlanadi.
    ctx = _ctx("uz")
    media2 = _Msg(photo=True)
    st2 = _run(MP.manual_preview_media_received(_update_msg(media2), ctx))
    check("media + eskirgan sessiya → mp_session_expired + END",
          st2 == ConversationHandler.END
          and _texts(media2)
          and _texts(media2)[-1] == manual_post_t("mp_session_expired", "uz"),
          str(_texts(media2))[:120])


# ============================================================================
# TEST 3 — REGRESSIYA: SMART EMOJI xulqi o'zgarmagan (hint YO'Q)
# ============================================================================
def test_preview_emoji_regression():
    print("\n== TEST 3: smart emoji — eski xulq (reaksiya saqlanadi, hint YO'Q) ==")
    ctx = _ctx("uz")
    try:
        _msg, _state, fake = _start_manual_flow(ctx)
        emoji_msg = _Msg(text="😎")
        st = _run(MP.manual_preview_emoji_received(_update_msg(emoji_msg), ctx))
        hint = manual_post_t("mp_stage_hint", "uz")
        check("😎 → reaksiya sifatida qabul (holat MANUAL_PREVIEW)",
              st == MP.MANUAL_PREVIEW
              and ctx.user_data.get(MP.UD_REACTIONS) == ["😎"],
              str(ctx.user_data.get(MP.UD_REACTIONS)))
        check("😎 → 💡 eslatma YUBORILMADI (qabul qilingan kiritma)",
              hint not in _texts(emoji_msg), str(_texts(emoji_msg))[:120])
        check("😎 → oxirgi xabar — yangilangan preview",
              _texts(emoji_msg)[-1] != hint and "😎" in _texts(emoji_msg)[-1],
              str(_texts(emoji_msg))[-80:])
    finally:
        fake.restore()


# ============================================================================
# TEST 4 — KANAL TANLASH: erkin matn/media → 💡 + tanlov klaviaturasi qayta
# ============================================================================
def test_channel_select_fallback():
    print("\n== TEST 4: kanal tanlash bosqichida — 💡 + klaviatura qayta ==")
    channels = [("-1001", "Kanal A"), ("-1002", "Kanal B")]
    ctx = _ctx("uz")
    fake = _FakeDB({"get_user_channels": channels, "add_post": 555})
    try:
        ctx.user_data[MP.UD_CONTENT] = "Post matni"
        ctx.user_data[MP.UD_POST_TYPE] = "text"
        # Ko'p kanal: 🚀 → kanal tanlash holati ochiladi.
        q = _Query(CB_MANUAL_NOW)
        st = _run(MP.manual_panel_callback(_update_query(q), ctx))
        check("ko'p kanal: 🚀 → MANUAL_CHANNEL_SELECT",
              st == MP.MANUAL_CHANNEL_SELECT, str(st))

        # Foydalanuvchi adashib erkin matn yozdi.
        free = _Msg(text="kanalni tanlay olmayapman")
        st2 = _run(MP.manual_channel_select_fallback(_update_msg(free), ctx))
        hint = manual_post_t("mp_stage_hint", "uz")
        check("erkin matn → holat SAQLANDI (MANUAL_CHANNEL_SELECT)",
              st2 == MP.MANUAL_CHANNEL_SELECT, str(st2))
        check("💡 eslatma yuborildi", _texts(free) and _texts(free)[0] == hint,
              str(_texts(free))[:120])
        last = free.sent[-1]
        cbs = _cbs(last["reply_markup"]) if last.get("reply_markup") else []
        check("kanal tanlov klaviaturasi QAYTA ko'rsatildi",
              manual_channel_callback("-1001") in cbs
              and manual_channel_callback("-1002") in cbs, str(cbs))

        # Media tashladi — bir xil yumshoq fallback.
        media = _Msg(photo=True)
        st3 = _run(MP.manual_channel_select_fallback(_update_msg(media), ctx))
        check("media → holat SAQLANDI + klaviatura qayta",
              st3 == MP.MANUAL_CHANNEL_SELECT
              and media.sent
              and media.sent[-1].get("reply_markup") is not None, str(st3))
    finally:
        fake.restore()

    # Kanallar bo'sh bo'lib qolsa — muloyim yopish (eski xulq).
    ctx2 = _ctx("uz")
    fake2 = _FakeDB({"get_user_channels": []})
    try:
        free2 = _Msg(text="x")
        st4 = _run(MP.manual_channel_select_fallback(_update_msg(free2), ctx2))
        check("kanalsiz → muloyim yopish (END + mp_no_channels)",
              st4 == ConversationHandler.END
              and _texts(free2)
              and _texts(free2)[-1] == manual_post_t("mp_no_channels", "uz"),
              str(_texts(free2))[:120])
    finally:
        fake2.restore()


# ============================================================================
# TEST 5 — REAKSIYA/HAVOLA BOSQICHLARIDA MEDIA: 💡 + yo'riqnoma qayta
# ============================================================================
def test_input_states_media_fallback():
    print("\n== TEST 5: reaksiya/havola kiritishda media — yumshoq fallback ==")
    ctx = _ctx("uz")
    try:
        _msg, _state, fake = _start_manual_flow(ctx)
        # ❤️ → custom kiritish holati.
        st = _run(MP.manual_panel_callback(
            _update_query(_Query(CB_MANUAL_REACT_CUSTOM)), ctx))
        check("custom reaksiya holati ochildi",
              st == MP.MANUAL_REACTION_CUSTOM, str(st))
        media = _Msg(photo=True)
        st2 = _run(MP.manual_reaction_custom_media_received(
            _update_msg(media), ctx))
        hint = manual_post_t("mp_stage_hint", "uz")
        check("reaksiyada media → holat SAQLANDI",
              st2 == MP.MANUAL_REACTION_CUSTOM, str(st2))
        check("reaksiyada media → 💡 eslatma + yo'riqnoma qayta",
              _texts(media)[0] == hint
              and manual_post_t("mp_react_custom_prompt", "uz")
              in _texts(media)[-1], str(_texts(media))[:160])

        # 🔗 havolali tugma holati.
        st3 = _run(MP.manual_panel_callback(
            _update_query(_Query(CB_MANUAL_URL_BTN)), ctx))
        check("havolali tugma holati ochildi",
              st3 == MP.MANUAL_URL_INPUT, str(st3))
        media2 = _Msg(photo=True)
        st4 = _run(MP.manual_url_media_received(_update_msg(media2), ctx))
        check("havolada media → holat SAQLANDI",
              st4 == MP.MANUAL_URL_INPUT, str(st4))
        check("havolada media → 💡 eslatma + yo'riqnoma qayta",
              _texts(media2)[0] == hint
              and manual_post_t("mp_url_prompt", "uz") in _texts(media2)[-1],
              str(_texts(media2))[:160])
    finally:
        fake.restore()


# ============================================================================
# TEST 6 — REGRESSIYA: matn kiritishdagi eski aniq xatolar o'zgarmagan
# ============================================================================
def test_input_states_text_regression():
    print("\n== TEST 6: eski aniq xato xabarlari saqlangan (hint YO'Q) ==")
    ctx = _ctx("uz")
    try:
        _msg, _state, fake = _start_manual_flow(ctx)
        ctx.user_data[MP.UD_MODE] = MP.MODE_TIME
        bad_time = _Msg(text="blablabla")
        st = _run(MP.manual_time_received(_update_msg(bad_time), ctx))
        check("noto'g'ri vaqt → mp_time_invalid (oxirgi xabar)",
              st == MP.MANUAL_TIME_INPUT
              and _texts(bad_time)
              and _texts(bad_time)[-1] == manual_post_t("mp_time_invalid", "uz"),
              str(_texts(bad_time))[:120])
    finally:
        fake.restore()

    ctx2 = _ctx("uz")
    try:
        _msg2, _state2, fake2 = _start_manual_flow(ctx2)
        bad_url = _Msg(text="javascript:alert(1)")
        st2 = _run(MP.manual_url_received(_update_msg(bad_url), ctx2))
        check("xavfli havola matni → mp_url_invalid (oxirgi xabar)",
              st2 == MP.MANUAL_URL_INPUT
              and _texts(bad_url)
              and _texts(bad_url)[-1] == manual_post_t("mp_url_invalid", "uz"),
              str(_texts(bad_url))[:120])
        bad_react = _Msg(text="bu emoji emas")
        st3 = _run(MP.manual_reaction_custom_received(
            _update_msg(bad_react), ctx2))
        check("emoji emas → mp_react_custom_invalid (oxirgi xabar)",
              st3 == MP.MANUAL_REACTION_CUSTOM
              and _texts(bad_react)
              and _texts(bad_react)[-1]
              == manual_post_t("mp_react_custom_invalid", "uz"),
              str(_texts(bad_react))[:120])
    finally:
        fake2.restore()


# ============================================================================
# TEST 7 — FSM ROUTING: yangi handlerlar ro'yxatdan o'tgan (filtr semantikasi)
# ============================================================================
def test_fsm_routing():
    print("\n== TEST 7: FSM routing — handlerlar ro'yxati va filtrlari ==")
    app = _build_app()
    conv = _main_conv(app)

    def _mh(state):
        return [h for h in conv.states.get(state, [])
                if isinstance(h, MessageHandler)]

    def _matches(handler, update):
        try:
            return bool(handler.check_update(update))
        except Exception:
            return False

    # MANUAL_PREVIEW: TEXT handler (smart emoji) + MEDIA handler (fallback).
    preview_mh = _mh(MP.MANUAL_PREVIEW)
    check("MANUAL_PREVIEW: TEXT handleri manual_preview_emoji_received",
          any(getattr(h, "callback", None) == MP.manual_preview_emoji_received
              for h in preview_mh), "")
    check("MANUAL_PREVIEW: MEDIA handleri manual_preview_media_received",
          any(getattr(h, "callback", None) == MP.manual_preview_media_received
              for h in preview_mh), "")
    emoji_h = next((h for h in preview_mh
                    if getattr(h, "callback", None)
                    == MP.manual_preview_emoji_received), None)
    media_h = next((h for h in preview_mh
                    if getattr(h, "callback", None)
                    == MP.manual_preview_media_received), None)
    if emoji_h is not None and media_h is not None:
        txt_upd = _tg_update(text="salom")
        photo_upd = _tg_update(photo=True)
        cmd_upd = _tg_update(text="/start", command=True)
        check("TEXT handler: matnni oladi, media/rasmni OLMAYDI",
              _matches(emoji_h, txt_upd) and not _matches(emoji_h, photo_upd),
              "")
        check("MEDIA handler: rasmni oladi, matnni OLMAYDI",
              _matches(media_h, photo_upd) and not _matches(media_h, txt_upd),
              "")
        check("MEDIA handler: buyruqni (/start) OLMAYDI",
              not _matches(media_h, cmd_upd), "")

    # MANUAL_CHANNEL_SELECT: fallback har qanday (buyruqsiz) xabarni oladi.
    ch_mh = _mh(MP.MANUAL_CHANNEL_SELECT)
    ch_h = next((h for h in ch_mh
                 if getattr(h, "callback", None)
                 == MP.manual_channel_select_fallback), None)
    check("MANUAL_CHANNEL_SELECT: fallback handleri ro'yxatda",
          ch_h is not None, "")
    if ch_h is not None:
        check("channel fallback: matn VA media ikkalasini oladi",
              _matches(ch_h, _tg_update(text="qaysi?"))
              and _matches(ch_h, _tg_update(photo=True)), "")
        check("channel fallback: buyruqni OLMAYDI",
              not _matches(ch_h, _tg_update(text="/start", command=True)), "")

    # Kiritish holatlari: media fallback handlerlari ro'yxatda.
    check("MANUAL_REACTION_CUSTOM: media fallback ro'yxatda",
          any(getattr(h, "callback", None)
              == MP.manual_reaction_custom_media_received
              for h in _mh(MP.MANUAL_REACTION_CUSTOM)), "")
    check("MANUAL_URL_INPUT: media fallback ro'yxatda",
          any(getattr(h, "callback", None) == MP.manual_url_media_received
              for h in _mh(MP.MANUAL_URL_INPUT)), "")
    react_media_h = next((h for h in _mh(MP.MANUAL_REACTION_CUSTOM)
                          if getattr(h, "callback", None)
                          == MP.manual_reaction_custom_media_received), None)
    url_media_h = next((h for h in _mh(MP.MANUAL_URL_INPUT)
                        if getattr(h, "callback", None)
                        == MP.manual_url_media_received), None)
    if react_media_h is not None:
        check("reaksiya media handler: rasmni oladi, matnni OLMAYDI",
              _matches(react_media_h, _tg_update(photo=True))
              and not _matches(react_media_h, _tg_update(text="😎")), "")
    if url_media_h is not None:
        check("havola media handler: rasmni oladi, matnni OLMAYDI",
              _matches(url_media_h, _tg_update(photo=True))
              and not _matches(url_media_h, _tg_update(text="https://t.me/x")),
              "")


# ============================================================================
# TEST 8 — i18n: mp_stage_hint 3 tilda (spetsifikatsiya matni + paritet)
# ============================================================================
def test_i18n_hint():
    print("\n== TEST 8: i18n — mp_stage_hint 3 tilda, paritet ==")
    from translations import manual_post_parity_report
    spec_uz = ("💡 Hozirgi bosqichda quyidagi tugmalardan birini "
               "tanlashingiz kerak:")
    check("uz matni — spetsifikatsiyaga AYNAN mos",
          manual_post_t("mp_stage_hint", "uz") == spec_uz,
          manual_post_t("mp_stage_hint", "uz"))
    values = {lang: manual_post_t("mp_stage_hint", lang) for lang in LANGS}
    check("3 tilda mavjud va FARQLI (tarjima)",
          all(v for v in values.values()) and len(set(values.values())) == 3,
          str(values))
    check("manual_post lug'ati pariteti in_sync",
          manual_post_parity_report()["in_sync"] is True, "")


# ============================================================================
def main():
    print("=" * 70)
    print(" 💡 FSM INPUT FALLBACK — MANUAL POST (PHASE 1) TESTLARI")
    print("=" * 70)
    test_preview_free_text()
    test_preview_media()
    test_preview_emoji_regression()
    test_channel_select_fallback()
    test_input_states_media_fallback()
    test_input_states_text_regression()
    test_fsm_routing()
    test_i18n_hint()
    print()
    if failures:
        print(f"❌ {failures} ta tekshiruv YIQILDI (jami {passed + failures})")
        sys.exit(1)
    print(f"✅ BARCHA FSM FALLBACK TESTLARI O'TDI ({passed} tekshiruv)")


if __name__ == "__main__":
    main()
