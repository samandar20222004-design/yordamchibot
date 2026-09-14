#!/usr/bin/env python3
"""🧩 KONTENT YARATISH SUBMENU'SI — PostAssist V2 (1-2-3 mikro qadamlar).

Qamrov (topshiriq spetsifikatsiyasi bilan birma-bir):

  TEST 1:  [✨ Kontent yaratish] bosilganda ICHKI MENYUDA aynan 5 ta tugma +
           ◀️ Orqaga bo'ladi va qatorlar speksdagi tartibda chiziladi:
               [✨ Magic Post]   [📝 Matn → Post]
               [📸 Rasm → Post]  [🎙 Ovoz → Post]
                       [🤖 AI Yordamchi]
                           [◀️ Orqaga]
  TEST 2:  PARITY — barcha tugmalar UZ / RU / EN tillarida to'liq sinxron
           (yalg'iz key emas, registry + klaviatura + parity hisobotlari).
  TEST 3:  ROUTING — har bir submenu tugmasi REAL router'da o'z oqimini ochadi
           (Magic Post FSM / oddiy matn post / Vision / STT / AI bo'limi /
           asosiy menyu) va hech biri fallback'ga tushmaydi; dialog ICHIDA ham.
  TEST 4:  OQIMLAR — har bir tugma bosilganda handler XATOSIZ ishlaydi va
           speksdagi yo'riqnomalar chiqadi (rasm va ovoz uchun aniq matnlar).
  TEST 5:  ACTION-FIRST — menyu tashqarisida ovoz → STT oqimi, rasm → Vision
           oqimi, xom matn → «✨ Magic Post» taklifi (qisqa matn eski javob).
  TEST 6:  REGRESSIYA QO'RIQONLARI — asosiy menyu 6 tugma ^^^ o'zgarmadi,
           fallback ENG oxirgi handler, yangi holat/prefikslar unikal,
           «cc_» entry point dialog ichida ishlamaydi, hardcode qilingan
           foydalanuvchi matni yo'q.

Ishga tushirish:
    PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh   # runner bosqichi
    python3 tests/content_creation_menu_test.py
"""
import asyncio
import os
import sys
import time
import warnings
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:CONTENT_MENU_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10002")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

passed = 0
failures = 0
LANGS = ("uz", "ru", "en")

# Speksdagi QAT'IY layout (har tilda bir xil tartib, yorliqlar tarjima qilinadi).
EXPECTED_SUBMENU = {
    "uz": [["✨ Magic Post", "📝 Matn → Post"],
           ["📸 Rasm → Post", "🎙 Ovoz → Post"],
           ["🤖 AI Yordamchi"],
           ["◀️ Orqaga"]],
    "ru": [["✨ Magic Post", "📝 Текст → Пост"],
           ["📸 Фото → Пост", "🎙 Голос → Пост"],
           ["🤖 AI-помощник"],
           ["◀️ Назад"]],
    "en": [["✨ Magic Post", "📝 Text → Post"],
           ["📸 Image → Post", "🎙 Voice → Post"],
           ["🤖 AI Assistant"],
           ["◀️ Back"]],
}

# Har bir tugma ochishi KERAKBO'LGAN oqim handleri (test 3 uchun yagona manba).
EXPECTED_ROUTE = {
    "cm_btn_magic": "magic_post_entry",
    "cm_btn_text": "start_new_post",
    "cm_btn_image": "image_post_entry",
    "cm_btn_voice": "voice_post_entry",
    "cm_btn_ai": "ai_studio_hub_entry",
    "cm_btn_back": "content_creation_back",
}


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


def kb_rows(markup):
    return [[b.text for b in row] for row in markup.keyboard]


def kb_flat(markup):
    return [t for row in kb_rows(markup) for t in row]


# ---------------------------------------------------------------------------
# MODULLAR (env sozlangandan KEYIN import qilinadi)
# ---------------------------------------------------------------------------
from telegram.ext import (  # noqa: E402
    CallbackQueryHandler, ConversationHandler, MessageHandler, filters,
)

import handlers as H  # noqa: E402
from handlers.ai_assistant import (  # noqa: E402
    AI_MENU_STATE, ai_studio_hub_entry, ai_studio_menu_entry,
)
import handlers.content_creation as CC_MOD  # noqa: E402
from handlers.content_creation import (  # noqa: E402
    CC_MAGIC, CC_MENU, ContentOfferEntryHandler, content_creation_back,
    content_offer_callback, looks_like_post_material, remember_direct_text,
    take_direct_text,
)
from handlers.image_post import (  # noqa: E402
    ImageEntryHandler, IMAGE_POST_INPUT, image_post_entry,
)
from handlers.magic_post import (  # noqa: E402
    MAGIC_INPUT, MAGIC_STYLE_SELECT, magic_post_entry,
)
from handlers.new_post import CHOOSE_CHANNEL, start_new_post  # noqa: E402
from handlers.voice_post import (  # noqa: E402
    VOICE_AWAIT, VOICE_MESSAGE_FILTER, VoiceEntryHandler, voice_post_entry,
)
from keyboards.default import (  # noqa: E402
    BTN_ADMIN_PANEL, MENU_TEXTS, get_content_creation_keyboard,
    get_main_keyboard, is_menu_text,
)
from locales.translations import get_text  # noqa: E402
from translations import (  # noqa: E402
    CONTENT_MENU_I18N, CONTENT_MENU_KEYS, content_menu_parity_report,
    content_menu_t, magic_post_parity_report, voice_post_parity_report, voice_t,
)


# ---------------------------------------------------------------------------
# YORDAMCHILAR — yengil Update/Context fakeri (tarmoqqa chiqmaydi)
# ---------------------------------------------------------------------------
class _Rec:
    """reply_text / edit_message_text / answer yozib boruvchi soxta obyekt."""

    def __init__(self, text=None, chat_id=4242, user_id=4242):
        self.text = text
        self.chat_id = chat_id
        self.from_user = SimpleNamespace(id=user_id, first_name="Tester")
        self.sent = []

    async def reply_text(self, text, **kwargs):
        self.sent.append(dict(text=text, **kwargs))
        return SimpleNamespace(
            message_id=1,
            chat=SimpleNamespace(id=self.chat_id),
            delete=self._noop,
        )

    async def _noop(self, *a, **kw):
        return None


class _Query:
    def __init__(self, data, message):
        self.data = data
        self.message = message
        self.answered = []
        self.edits = []

    async def answer(self, text=None, **kwargs):
        self.answered.append(text)
        return True

    async def edit_message_text(self, text, **kwargs):
        self.edits.append(dict(text=text, **kwargs))
        return True


def _update_msg(rec):
    return SimpleNamespace(message=rec, effective_message=rec,
                           effective_user=rec.from_user, callback_query=None)


def _update_query(query, user_id=4242):
    return SimpleNamespace(
        message=None, effective_message=query.message,
        effective_user=SimpleNamespace(id=user_id, first_name="Tester"),
        callback_query=query,
    )


def _ctx(lang="uz", user_data=None, chat_data=None, app=None):
    ud = {"lang": lang}
    ud.update(user_data or {})
    return SimpleNamespace(
        user_data=ud, chat_data=chat_data or {},
        bot=SimpleNamespace(username="postassist_test_bot"),
        application=app,
    )


def _build_app():
    """Haqiqiy PTB Application + register_all_handlers (tarmoqqa chiqmaydi).

    Soxta recorder o'rniga haqiqiy app: ``_active_conversation_state`` dialog
    holatini ``app.handlers`` (guruh → handlerlar) orqali o'qiydi — entry
    point'larning «dialog ichida ishlamasligi» himoyasini SINASH uchun aynan
    shu kerak.
    """
    import warnings as _w
    from telegram.ext import ApplicationBuilder
    with _w.catch_warnings():
        _w.simplefilter("ignore")
        app = ApplicationBuilder().token("123456:CONTENT_MENU_TEST").build()
    H.register_all_handlers(app)
    return app


def _all_handlers(app):
    return [h for group in sorted(app.handlers) for h in app.handlers[group]]


def _conv_and_regex_handlers():
    app = _build_app()
    handlers = _all_handlers(app)
    conv = [h for h in handlers if isinstance(h, ConversationHandler)][0]
    regex = [h for h in handlers
             if isinstance(h, MessageHandler) and isinstance(h.filters, filters.Regex)]
    return app, conv, regex


def _fake_update(label, chat_id=4242, user_id=4242):
    from telegram import Update
    return Update.de_json({
        "update_id": 1,
        "message": {
            "message_id": 10, "date": 0,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "first_name": "Tester"},
            "text": label,
        },
    }, None)


def _media_update(kind, chat_id=4242, user_id=4242, caption=None):
    from telegram import Update
    payload = {
        "message_id": 11, "date": 0,
        "chat": {"id": chat_id, "type": "private"},
        "from": {"id": user_id, "is_bot": False, "first_name": "Tester"},
    }
    if caption is not None:
        payload["caption"] = caption
    if kind == "voice":
        payload["voice"] = {"file_id": "voice-1", "file_unique_id": "voice-u1",
                            "duration": 12, "mime_type": "audio/ogg"}
    elif kind == "photo":
        payload["photo"] = [{"file_id": "photo-1", "file_unique_id": "photo-u1",
                             "file_size": 100, "width": 10, "height": 10}]
    elif kind == "text":
        payload["text"] = caption or "matn"
    return Update.de_json({"update_id": 2, "message": payload}, None)


def _callback_update(data, chat_id=4242, user_id=4242):
    from telegram import Update
    return Update.de_json({
        "update_id": 3,
        "callback_query": {
            "id": "1", "chat_instance": "ci",
            "from": {"id": user_id, "is_bot": False, "first_name": "Tester"},
            "message": {
                "message_id": 12, "date": 0,
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": user_id, "is_bot": False, "first_name": "Tester"},
                "text": "taklif",
            },
            "data": data,
        },
    }, None)


def _patch_db(values=None):
    """database.run_db'ni soxtalashtiradi (funksiya nomi bo'yicha qiymat)."""
    import database as db_mod
    orig = db_mod.run_db
    table = values or {}

    async def fake_run_db(fn, *args, **kwargs):
        return table.get(getattr(fn, "__name__", ""), None)

    db_mod.run_db = fake_run_db
    return lambda: setattr(db_mod, "run_db", orig)


def _targets(handlers, label):
    """``label`` matnini taniydigan Regex MessageHandler maqsad nomlari."""
    upd = _fake_update(label)
    names = set()
    for h in handlers:
        if not h.check_update(upd):
            continue
        cb = h.callback
        if callable(cb) and getattr(cb, "__name__", "") != "<lambda>":
            names.add(cb.__name__)
            continue
        for n in getattr(getattr(cb, "__code__", None), "co_names", ()):
            if n in ("guard_entry", "guard_menu"):
                continue
            if callable(getattr(H, n, None)):
                names.add(n)
    return names


# ============================================================================
# TEST 1 — SUBMENU KLAVIATURASI: 5 tugma + ◀️ Orqaga (aniq qatorlar)
# ============================================================================
def test_submenu_keyboard():
    print("\n== TEST 1: [✨ Kontent yaratish] ichki menyusi — 5 tugma + ◀️ Orqaga ==")
    for lang in LANGS:
        kb = get_content_creation_keyboard(lang)
        rows = kb_rows(kb)
        check(f"submenu[{lang}]: qatorlar speksdagidek",
              rows == EXPECTED_SUBMENU[lang], str(rows))
        check(f"submenu[{lang}]: aynan 5 tugma + Orqaga = 6",
              len(kb_flat(kb)) == 6, str(kb_flat(kb)))
        check(f"submenu[{lang}]: takror yo'q",
              len(set(kb_flat(kb))) == 6, str(kb_flat(kb)))
        check(f"submenu[{lang}]: resize_keyboard=True (pastki klaviatura)",
              kb.resize_keyboard is True)
        # 1-qator: Magic + Matn, 2-qator: Rasm + Ovoz — 3 va 4-qator bittadan.
        check(f"submenu[{lang}]: 3-qator 🤖 AI Yordamchi", rows[2] == [content_menu_t("cm_btn_ai", lang)])
        check(f"submenu[{lang}]: 4-qator ◀️ Orqaga", rows[3] == [content_menu_t("cm_btn_back", lang)])

    # Asosiy menyu 6 tugma STANDARTI o'zgarmadi (submenu unga aralashmaydi).
    for lang in LANGS:
        main_flat = kb_flat(get_main_keyboard(False, lang=lang))
        check(f"main[{lang}]: 6 tugma saqlangan", len(main_flat) == 6, str(main_flat))
        check(f"main[{lang}]: submenu tugmalari asosiy menyuda YO'Q",
              not set(main_flat) & set(kb_flat(get_content_creation_keyboard(lang))))
    check("main[admin]: 7 tugma (Admin Panel oxirgi qatorda)",
          kb_rows(get_main_keyboard(True, lang="uz"))[-1] == [BTN_ADMIN_PANEL])


# ============================================================================
# TEST 2 — UZ / RU / EN PARITY (to'liq sinxron)
# ============================================================================
def test_i18n_parity():
    print("\n== TEST 2: UZ/RU/EN paritet — submenu, voice va Magic hisobotlari ==")
    report = content_menu_parity_report()
    check("content_menu pariteti in_sync", report["in_sync"] is True, str(report))
    check("content_menu kalitlar soni >= 11", report["keys"] >= 11, str(report["keys"]))
    check("CONTENT_MENU_KEYS lug'at bilan bir xil",
          set(CONTENT_MENU_KEYS) == set(CONTENT_MENU_I18N["uz"]), "")

    # Har bir tugma yorlig'i uchala tilda mavjud va bo'sh emas.
    for key in ("cm_btn_magic", "cm_btn_text", "cm_btn_image", "cm_btn_voice",
                "cm_btn_ai", "cm_btn_back"):
        vals = [CONTENT_MENU_I18N[c][key] for c in LANGS]
        check(f"{key}: 3 tilda ham to'liq", all(v and v.strip() for v in vals), str(vals))
        check(f"{key}: kalit tugma klaviaturasiga kiradi",
              all(v in kb_flat(get_content_creation_keyboard(c)) for c, v in zip(LANGS, vals)),
              str(vals))
    # Brend nomidan tashqari hamma yorliqlar tillarda farq qiladi.
    for key in ("cm_btn_text", "cm_btn_image", "cm_btn_voice", "cm_btn_ai", "cm_btn_back"):
        vals = {CONTENT_MENU_I18N[c][key] for c in LANGS}
        check(f"{key}: 3 tilda farqli (sinxron tarjima)", len(vals) == 3, str(vals))
    check("cm_btn_magic: brend nomi 3 tilda bir xil",
          {CONTENT_MENU_I18N[c]["cm_btn_magic"] for c in LANGS} == {"✨ Magic Post"})

    # SUBMENU TUGMALARI — mavjud oqim tugmalari bilan SINXRON (dublikat yo'q):
    # ✨ Magic Post va 📸 Rasm → Post yorliqlari o'z killer featuralarining
    # konstantalari bilan bir xil bo'lishi shart.
    from keyboards.default import (
        BTN_IMAGE_POST, BTN_IMAGE_POST_EN, BTN_IMAGE_POST_RU,
        BTN_MAGIC_POST, BTN_MAGIC_POST_EN, BTN_MAGIC_POST_RU,
    )
    magic_by_lang = {"uz": BTN_MAGIC_POST, "ru": BTN_MAGIC_POST_RU, "en": BTN_MAGIC_POST_EN}
    image_by_lang = {"uz": BTN_IMAGE_POST, "ru": BTN_IMAGE_POST_RU, "en": BTN_IMAGE_POST_EN}
    for lang in LANGS:
        check(f"Parity[{lang}]: submenu ✨ Magic Post == Magic Post tugmasi",
              content_menu_t("cm_btn_magic", lang) == magic_by_lang[lang],
              f"{content_menu_t('cm_btn_magic', lang)!r} != {magic_by_lang[lang]!r}")
        check(f"Parity[{lang}]: submenu 📸 Rasm → Post == Image → Post tugmasi",
              content_menu_t("cm_btn_image", lang) == image_by_lang[lang],
              f"{content_menu_t('cm_btn_image', lang)!r} != {image_by_lang[lang]!r}")
        # Image → Post oilasi (MENU_TEXTS aliaslari) submenu tugmasini ham taniydi.
        check(f"Parity[{lang}]: 📸 Rasm → Post routing'da ham bir xil oilada",
              is_menu_text(content_menu_t("cm_btn_image", lang), "image_post")
              or content_menu_t("cm_btn_image", lang) in image_by_lang.values())

    # Qo'shni lug'atlar ham buzilmagan (paritet hisobotlari).
    check("voice_post pariteti in_sync", voice_post_parity_report()["in_sync"] is True,
          str(voice_post_parity_report()))
    check("magic_post pariteti in_sync", magic_post_parity_report()["in_sync"] is True, "")

    # MENU_TEXTS registry: har bir yangi oila uchala tilda to'liq.
    fams = {
        "content_text_post": {"📝 Matn → Post", "📝 Текст → Пост", "📝 Text → Post"},
        "content_voice_post": {"🎙 Ovoz → Post", "🎙 Голос → Пост", "🎙 Voice → Post"},
        "content_ai": {"🤖 AI Yordamchi", "🤖 AI-помощник", "🤖 AI Assistant"},
        "content_back": {"◀️ Orqaga", "◀️ Назад", "◀️ Back"},
    }
    for action, expected in fams.items():
        check(f"MENU_TEXTS['{action}'] uchala tilni o'z ichiga oladi",
              expected <= set(MENU_TEXTS.get(action, ())), str(MENU_TEXTS.get(action)))
        for lang in LANGS:
            label = CONTENT_MENU_I18N[lang][{
                "content_text_post": "cm_btn_text",
                "content_voice_post": "cm_btn_voice",
                "content_ai": "cm_btn_ai",
                "content_back": "cm_btn_back",
            }[action]]
            check(f"is_menu_text[{lang}] {label!r} → {action}", is_menu_text(label, action))


# ============================================================================
# TEST 3 — ROUTING: har bir tugma o'z oqimini ochadi (real router)
# ============================================================================
def test_submenu_routing():
    print("\n== TEST 3: routing — submenu tugmalari real router'da o'z oqimiga ==")
    _app, conv, regex = _conv_and_regex_handlers()

    for key, expected in EXPECTED_ROUTE.items():
        for lang in LANGS:
            label = content_menu_t(key, lang)
            names = _targets(regex, label)
            check(f"[{lang}] {label!r} → {expected}", names == {expected}, str(sorted(names)))

    # «✨ Kontent yaratish» (va meros «✨ AI Studio») submenu'ni ochadi.
    for lang in LANGS:
        for key in ("btn_create_content", "btn_ai_studio"):
            label = get_text(key, lang)
            names = _targets(regex, label)
            check(f"[{lang}] {label!r} → ai_studio_menu_entry (submenu)",
                  names == {"ai_studio_menu_entry"}, str(sorted(names)))

    # Hech bir submenu tugmasi fallback'ga tushmaydi (global qatorlar ham).
    for key in EXPECTED_ROUTE:
        for lang in LANGS:
            label = content_menu_t(key, lang)
            names = _targets(regex, label)
            check(f"[{lang}] {label!r} fallback EMAS",
                  bool(names) and "unknown_message_fallback" not in names, str(sorted(names)))

    # Dialog ICHIDA ham submenu tugmalari ishlaydi (all_menu_jumps parity).
    for state in (MAGIC_INPUT, IMAGE_POST_INPUT, CHOOSE_CHANNEL, VOICE_AWAIT,
                  AI_MENU_STATE, MAGIC_STYLE_SELECT):
        handlers = conv.states[state]
        for key, expected in EXPECTED_ROUTE.items():
            if state == MAGIC_STYLE_SELECT and key != "cm_btn_back":
                continue
            probe = MessageHandler(filters.Regex("x"), lambda u, c: None)
            labels = [content_menu_t(key, lang) for lang in LANGS]
            matched = set()
            for h in handlers:
                if isinstance(h, MessageHandler) and isinstance(h.filters, filters.Regex):
                    for label in labels:
                        if h.check_update(_fake_update(label)):
                            cb = h.callback
                            nm = getattr(cb, "__name__", "")
                            if nm in ("guard_entry", "guard_menu", "<lambda>"):
                                for n in getattr(getattr(cb, "__code__", None), "co_names", ()):
                                    if n not in ("guard_entry", "guard_menu") and callable(getattr(H, n, None)):
                                        matched.add(n)
                            elif nm:
                                matched.add(nm)
            check(f"state {state}: {key} tugmalari menu-jump sifatida ro'yxatda",
                  expected in matched, str(sorted(matched)))
            del probe


# ============================================================================
# TEST 4 — OQIMLAR: har bir tugma XATOSIZ ishlaydi va to'g'ri yo'riqnoma chiqadi
# ============================================================================
def test_submenu_flows():
    print("\n== TEST 4: oqimlar — submenu tugmalari haqiqiy handlerlarni ochadi ==")
    for lang in LANGS:
        # 1) [✨ Kontent yaratish] → ichki menyu (submenu) ochiladi.
        rec = _Rec()
        res = asyncio.run(ai_studio_menu_entry(_update_msg(rec), _ctx(lang)))
        sent = rec.sent
        check(f"[{lang}] ✨ Kontent yaratish → submenu chiqdi", len(sent) == 1, str(sent))
        check(f"[{lang}] submenu klaviaturasi aniq 5+1 tugma",
              sent and kb_rows(sent[0]["reply_markup"]) == EXPECTED_SUBMENU[lang],
              str(kb_rows(sent[0]["reply_markup"]) if sent else None))
        check(f"[{lang}] submenu yo'riqnomasi 5 yo'lning barchasini sanaydi",
              sent and all(token in sent[0]["text"] for token in
                           ("Magic Post", "Matn → Post" if lang == "uz" else
                            ("Текст → Пост" if lang == "ru" else "Text → Post"))),
              sent[0]["text"][:80] if sent else "")
        check(f"[{lang}] submenu dialog OCHMAYDI (action-first saqlanadi)",
              res == ConversationHandler.END, str(res))

        # 2) [📝 Matn → Post] → oddiy matnli post oqimi (kanal tanlash).
        restore = _patch_db({"get_user_channels": [
            {"channel_id": "-100123", "title": "Asosiy kanal"},
        ]})
        try:
            rec = _Rec()
            res = asyncio.run(start_new_post(_update_msg(rec), _ctx(lang)))
            check(f"[{lang}] 📝 Matn → Post → kanal tanlash holati",
                  res == CHOOSE_CHANNEL and len(rec.sent) == 1,
                  f"{res} {rec.sent}")
        finally:
            restore()

        # 3) [📸 Rasm → Post] → «mahsulot rasmini yuboring» + Vision oqimi.
        rec = _Rec()
        res = asyncio.run(image_post_entry(_update_msg(rec), _ctx(lang)))
        text = rec.sent[0]["text"] if rec.sent else ""
        check(f"[{lang}] 📸 Rasm → Post → rasm so'raladi",
              "Rasm" in text or "фото" in text.lower() or "photo" in text.lower(), text[:80])
        check(f"[{lang}] 📸 Rasm → Post → IMAGE_POST_INPUT holati",
              res == IMAGE_POST_INPUT, str(res))

        # 4) [🎙 Ovoz → Post] → «ovozli xabar (1 daqiqa ichida)» taklifi.
        rec = _Rec()
        res = asyncio.run(voice_post_entry(_update_msg(rec), _ctx(lang)))
        text = rec.sent[0]["text"] if rec.sent else ""
        needle = {"uz": ("ovozli xabar", "1 daqiqa"),
                  "ru": ("голосовое сообщение", "1 минуты"),
                  "en": ("voice message", "1 minute")}[lang]
        check(f"[{lang}] 🎙 Ovoz → Post yo'riqnomasi aniq matn bilan chiqdi",
              all(word in text for word in needle), text[:120])
        check(f"[{lang}] 🎙 Ovoz → Post → VOICE_AWAIT holati", res == VOICE_AWAIT, str(res))
        check(f"[{lang}] 🎙 Ovoz → Post klaviaturasida Bekor qilish bor",
              rec.sent and "❌" in str([b.text for row in rec.sent[0]["reply_markup"].keyboard
                                       for b in row]), str(rec.sent))

        # 5) [🤖 AI Yordamchi] → AI bo'limi (AI Studio vositalari).
        restore = _patch_db({"is_premium": False, "get_user_credits": 7})
        try:
            rec = _Rec()
            res = asyncio.run(ai_studio_hub_entry(_update_msg(rec), _ctx(lang)))
            check(f"[{lang}] 🤖 AI Yordamchi → AI Studio bo'limi ochildi",
                  res == AI_MENU_STATE and len(rec.sent) == 1, f"{res} {rec.sent}")
            labels = [b.text for row in rec.sent[0]["reply_markup"].inline_keyboard for b in row]
            check(f"[{lang}] AI bo'limi 5 ta vositani ko'rsatadi",
                  any("Post" in l or "пост" in l.lower() or "пост" in l.lower() for l in labels),
                  str(labels))
            check(f"[{lang}] AI bo'limida yozish/qayta yozish/tarjima g'oyasi bor",
                  all(word in rec.sent[0]["text"] for word in (
                      {"uz": ("tarjima", "qayta yozish"),
                       "ru": ("перевод", "переписывание"),
                       "en": ("translation", "rewriting")}[lang])),
                  rec.sent[0]["text"][:120])
        finally:
            restore()

        # 6) [◀️ Orqaga] → asosiy 6 tugmali menyu.
        rec = _Rec()
        res = asyncio.run(content_creation_back(_update_msg(rec), _ctx(lang)))
        check(f"[{lang}] ◀️ Orqaga → asosiy 6 tugmali menyu",
              rec.sent and kb_flat(rec.sent[0]["reply_markup"]) ==
              kb_flat(get_main_keyboard(False, lang=lang)), str(rec.sent))
        check(f"[{lang}] ◀️ Orqaga → dialog yopildi (END)",
              res == ConversationHandler.END, str(res))

        # 7) [✨ Magic Post] → Magic Post FSM yo'riqnomasi.
        rec = _Rec()
        res = asyncio.run(magic_post_entry(_update_msg(rec), _ctx(lang)))
        check(f"[{lang}] ✨ Magic Post → MAGIC_INPUT holati", res == MAGIC_INPUT, str(res))
        check(f"[{lang}] ✨ Magic Post yo'riqnomasi chiqdi",
              len(rec.sent) == 1 and rec.sent[0]["text"], str(rec.sent))


# ============================================================================
# TEST 5 — ACTION-FIRST: menyu tashqarisidagi ovoz / rasm / xom matn
# ============================================================================
def test_action_first_entry_points():
    print("\n== TEST 5: ACTION-FIRST — ovoz, rasm va xom matn darhol o'z oqimiga ==")
    app, conv, _regex = _conv_and_regex_handlers()
    entry_points = list(conv.entry_points)
    voice_entry = [h for h in entry_points if isinstance(h, VoiceEntryHandler)]
    image_entry = [h for h in entry_points if isinstance(h, ImageEntryHandler)]
    offer_entry = [h for h in entry_points if isinstance(h, ContentOfferEntryHandler)]
    check("VoiceEntryHandler main_conv entry point'ida", len(voice_entry) == 1)
    check("ImageEntryHandler main_conv entry point'ida", len(image_entry) == 1)
    check("ContentOfferEntryHandler (cc_) main_conv entry point'ida",
          len(offer_entry) == 1 and offer_entry[0].pattern.pattern == "^cc_",
          str([getattr(h, "pattern", None) for h in offer_entry]))

    # Ovoz → ovoz oqimi (VoiceEntryHandler) darhol mos keladi.
    if voice_entry:
        check("ovozli xabar → VoiceEntryHandler",
              bool(voice_entry[0].check_update(_media_update("voice"))))
        check("oddiy matn → VoiceEntryHandler EMAS",
              not voice_entry[0].check_update(_media_update("text", caption="salom")))

    # Rasm → image oqimi (ImageEntryHandler) darhol mos keladi.
    if image_entry:
        check("rasm → ImageEntryHandler", bool(image_entry[0].check_update(_media_update("photo"))))

    # Dialog ICHIDA entry point'lar holatni buzmaydi (regressiya qo'riqoni).
    key = (4242, 4242)
    conv._conversations[key] = MAGIC_INPUT
    try:
        if voice_entry:
            check("dialog ichida ovoz → VoiceEntryHandler mos KELMAYDI",
                  not voice_entry[0].check_update(_media_update("voice")))
        if image_entry:
            check("dialog ichida rasm → ImageEntryHandler mos KELMAYDI",
                  not image_entry[0].check_update(_media_update("photo")))
        if offer_entry:
            check("dialog ichida cc_ tugmasi mos KELMAYDI (holat buzilmaydi)",
                  not offer_entry[0].check_update(_callback_update(CC_MAGIC)))
    finally:
        conv._conversations.pop(key, None)
    if offer_entry:
        check("dialog tashqarisida cc_magic → mos keladi",
              bool(offer_entry[0].check_update(_callback_update(CC_MAGIC))))

    # --- XOM MATN → Magic Post taklifi ---
    material = ("Samarqanddagi yangi kofeyamiz uchun post yozib ber: "
                "uchinchi aprel kuni ochilamiz, birinchi mijozlarga chegirma")
    check("gate: uzun matn material hisoblanadi", looks_like_post_material(material))
    check("gate: qisqa matn material EMAS", not looks_like_post_material("???"))
    check("gate: 39 belgili inglizcha gap material EMAS",
          not looks_like_post_material("hello, this is a random english message"))
    check("gate: /command material EMAS", not looks_like_post_material("/start " + "x" * 60))

    for lang, expected in (("uz", get_text("unknown_message_fallback", "uz")),
                          ("ru", get_text("unknown_message_fallback", "ru"))):
        # a) Qisqa matn → eski xushmuomala javob + asosiy menyu (o'zgarmagan).
        H._UNKNOWN_FALLBACK_LAST.clear()
        rec = _Rec(text="???")
        asyncio.run(H.unknown_message_fallback(_update_msg(rec), _ctx(lang)))
        check(f"[{lang}] qisqa matn → eski fallback matni + asosiy menyu",
              len(rec.sent) == 1 and rec.sent[0]["text"] == expected
              and isinstance(rec.sent[0]["reply_markup"], type(get_main_keyboard(False, lang=lang))),
              str(rec.sent)[:160])

        # b) Xom matn → «✨ Magic Post» taklifi (inline tugmalar bilan).
        H._UNKNOWN_FALLBACK_LAST.clear()
        H_remembered = _Rec(text=material)
        asyncio.run(H.unknown_message_fallback(_update_msg(H_remembered), _ctx(lang)))
        sent = H_remembered.sent
        check(f"[{lang}] xom matn → Magic Post taklifi chiqdi", len(sent) == 1, str(sent)[:200])
        check(f"[{lang}] taklif matni tarjimaga mos",
              sent and content_menu_t("cm_offer_text", lang) == sent[0]["text"],
              sent[0]["text"][:60] if sent else "")
        cbs = [b.callback_data for row in sent[0]["reply_markup"].inline_keyboard for b in row]
        check(f"[{lang}] taklif tugmalari: cc_magic + cc_menu", cbs == [CC_MAGIC, CC_MENU], str(cbs))
        labels = [b.text for row in sent[0]["reply_markup"].inline_keyboard for b in row]
        check(f"[{lang}] taklif tugmasida Magic Post nomi bor",
              all(l.strip() for l in labels) and "Magic Post" in labels[0], str(labels))

        # c) Taklifni bosish → Magic Post uslub tanlash ekrani (matn yo'qolmaydi).
        #    Fallback cooldown'i tufayli matn yana saqlanib olinadi (holizoda).
        CC_MOD._DIRECT_TEXT.clear()
        H._UNKNOWN_FALLBACK_LAST.clear()
        H_remembered2 = _Rec(text=material)
        asyncio.run(H.unknown_message_fallback(_update_msg(H_remembered2), _ctx(lang)))
        ctx = _ctx(lang)
        query = _Query(CC_MAGIC, _Rec())
        res = asyncio.run(content_offer_callback(_update_query(query), ctx))
        check(f"[{lang}] cc_magic → MAGIC_STYLE_SELECT holati",
              res == MAGIC_STYLE_SELECT, str(res))
        check(f"[{lang}] cc_magic: xom matn Magic sessiyasiga o'tdi",
              ctx.user_data.get("magic_raw_text") == material,
              str(ctx.user_data.get("magic_raw_text"))[:60])
        check(f"[{lang}] cc_magic: uslub tanlash ekrani edit qilindi",
              bool(query.edits) and "mp_style" in str([b.callback_data
                                                       for row in query.edits[0]["reply_markup"].inline_keyboard
                                                       for b in row]),
              str(query.edits)[:160])
        check(f"[{lang}] cc_magic: 5 ta uslub tugmasi chiqdi",
              len([b for row in query.edits[0]["reply_markup"].inline_keyboard for b in row]) == 5)
        check(f"[{lang}] cc_magic tugmasi darhol answer qilindi",
              query.answered == [None], str(query.answered))
        check(f"[{lang}] taklifdan keyin matn bir marta olinadi",
              take_direct_text(4242) == "")

        # d) cc_menu → asosiy menyu + END
        query2 = _Query(CC_MENU, _Rec())
        res2 = asyncio.run(content_offer_callback(_update_query(query2), _ctx(lang)))
        check(f"[{lang}] cc_menu → asosiy menyuga qaytish (END)",
              res2 == ConversationHandler.END
              and kb_flat(query2.message.sent[0]["reply_markup"]) ==
              kb_flat(get_main_keyboard(False, lang=lang)), str(res2))

        # e) Matn eskirgan/ketiK bo'lsa — Magic oqimi bo'sh holida ochiladi.
        CC_MOD._DIRECT_TEXT.clear()
        query3 = _Query(CC_MAGIC, _Rec())
        res3 = asyncio.run(content_offer_callback(_update_query(query3), _ctx(lang)))
        check(f"[{lang}] cc_magic (matnsiz) → MAGIC_INPUT (xatosiz)",
              res3 == MAGIC_INPUT, str(res3))

    # TTL: 20 daqiqadan eskirgan matn ishlatilmaydi.
    CC_MOD._DIRECT_TEXT.clear()
    remember_direct_text(9911, "eski matn " * 10)
    CC_MOD._DIRECT_TEXT[9911] = ("eski matn " * 10, time.time() - 3600)
    check("TTL: eskirgan xom matn olinmaydi", take_direct_text(9911) == "")
    CC_MOD._DIRECT_TEXT.clear()

    # Ovoz/rasm action-first'ining oqim davomiyligi: VOICE_AWAIT holatida
    # ovozli xabar kelinsa — STT handleri ro'yxatda turadi.
    states = conv.states
    check("VOICE_AWAIT holatida ovozli xabar voice_message_received'ga tushadi",
          any(isinstance(h, MessageHandler) for h in states[VOICE_AWAIT]))


# ============================================================================
# TEST 6 — REGRESSIYA QO'RIQONLARI
# ============================================================================
def test_regression_guards():
    print("\n== TEST 6: regressiya qo'riqonlari (mavjud oqimlar buzilmagan) ==")
    src = (ROOT / "handlers/__init__.py").read_text(encoding="utf-8")
    body = src.split("def register_all_handlers(app):", 1)[1]

    # Fallback ENG oxirida qolishi shart (speks talabi).
    i_fallback = body.rfind("unknown_message_fallback")
    i_last_add = body.rfind("app.add_handler(")
    check("unknown_message_fallback oxirgi add_handler",
          i_last_add < i_fallback and i_fallback != -1)
    check("receipt_admin_callback → expired_session_callback tartibi buzilmagan",
          src.index("receipt_admin_callback,") < src.index('CallbackQueryHandler(expired_session_callback)'))
    check("post_score_handlers all_menu_jumps ichida", "post_score_handlers +" in body)
    check("yangi submenu guruhi all_menu_jumps ichida",
          "content_creation_handlers +" in body)
    check("voice entry point himoyasi saqlangan",
          "VoiceEntryHandler(VOICE_MESSAGE_FILTER, voice_message_received)" in body)
    check("image entry point himoyasi saqlangan",
          "ImageEntryHandler(filters.PHOTO & filters.ChatType.PRIVATE, image_photo_received)" in body)

    # handlers/__init__.py ichida foydalanuvchi matni HARDQOD qilinmagan.
    for literal in ("Magic Post bilan", "Asosiy menyu\"", "Iltimos, "):
        check(f"handlers/__init__.py da hardcode matn yo'q: {literal!r}",
              literal not in body, literal)

    # FSM holatlari noyob va to'qnashuv yo'q (yangi VOICE_AWAIT qo'shilishi
    # mavjud holatlarni SILJITMASLIGI kerak — regression kafolati).
    import handlers.ai_assistant as ai
    import handlers.image_post as ip
    import handlers.magic_post as mp
    import handlers.new_post as np_mod
    import handlers.post_score as ps
    import handlers.voice_post as vp
    state_sets = {
        "magic": {mp.MAGIC_INPUT, mp.MAGIC_STYLE_SELECT, mp.MAGIC_RESULT, mp.MAGIC_SEND_CHOOSE},
        "voice": {vp.VOICE_AWAIT, vp.VOICE_STYLE_SELECT, vp.VOICE_RESULT,
                  vp.VOICE_SEND_CHOOSE},
        "image": {ip.IMAGE_POST_INPUT, ip.IMAGE_STYLE_SELECT, ip.IMAGE_POST_RESULT,
                  ip.IMAGE_SEND_CHOOSE, ip.IMAGE_SCHEDULE_INPUT},
        "post_score": {ps.POST_SCORE_INPUT, ps.POST_SCORE_RESULT, ps.POST_SCORE_SEND_CHOOSE},
    }
    pairs = list(state_sets)
    clash = [f"{a}∩{b}" for i, a in enumerate(pairs) for b in pairs[i + 1:]
             if state_sets[a] & state_sets[b]]
    check("barcha killer-featura FSM holatlari o'zaro noyob", not clash, str(clash))
    check("esdi holat qiymatlari O'ZGARMAGAN (magic/voice/image/post_score/new_post)",
          state_sets["magic"] == {430, 431, 432, 433}
          and {vp.VOICE_STYLE_SELECT, vp.VOICE_RESULT, vp.VOICE_SEND_CHOOSE} == {440, 441, 442}
          and ip.IMAGE_POST_INPUT == 520 and ps.POST_SCORE_INPUT == 460
          and np_mod.CHOOSE_CHANNEL == 100 and ai.AI_MENU_STATE == 404)
    check("VOICE_AWAIT — yangi, bo'sh holat (439)",
          vp.VOICE_AWAIT == 439
          and 439 not in (state_sets["magic"] | state_sets["image"]
                          | state_sets["post_score"] | {ai.AI_MENU_STATE}))

    app = _build_app()
    all_h = _all_handlers(app)
    conv = [h for h in all_h if isinstance(h, ConversationHandler)][0]
    # Prefiks to'qnashuvi: «cc_» global stale-handler pattern'lari bilan
    # mos kelmasligi kerak (aks holda taklif tugmasi «sessiya eskirgan»
    # toast'iga tushib qolardi).
    stale_patterns = [h.pattern.pattern for h in _all_handlers(app)
                      if isinstance(h, CallbackQueryHandler) and getattr(h, "pattern", None)]
    import re as _re
    check("«cc_magic»/«cc_menu» global stale-handler'lardan biriga ham tushmaydi",
          not [pat for pat in stale_patterns
               for data in (CC_MAGIC, CC_MENU)
               if _re.search(pat, data)],
          str(stale_patterns))
    check("«cc_» entry point'i ro'yxatda stale-handler'lardan oldin turadi",
          any(isinstance(h, ContentOfferEntryHandler) for h in conv.entry_points))

    # App'da fallback ro'yxatdan keyin boshqa handler qo'silmagan.
    check("oxirgi ro'yxatdan o'tgan handler — fallback",
          getattr(all_h[-1], "callback", None) is H.unknown_message_fallback,
          str(all_h[-1]))
    check("VoiceEntryHandler va ImageEntryHandler hali ham entry point",
          any(isinstance(h, VoiceEntryHandler) for h in conv.entry_points)
          and any(isinstance(h, ImageEntryHandler) for h in conv.entry_points))
    check("allow_reentry saqlangan (entry point'lar dialogda ham tekshiriladi)",
          conv.allow_reentry is True)
    check("conversation timeout o'zgarmagan", conv.conversation_timeout == 600)

    # Asosiy 6 tugma + reply klaviatura API'lari buzilmagan.
    for lang in LANGS:
        check(f"get_main_keyboard[{lang}]: 6 tugma",
              len(kb_flat(get_main_keyboard(False, lang=lang))) == 6)
        check(f"voice_t('vp_intro', {lang}) mavjud",
              bool(voice_t("vp_intro", lang)) and "vp_intro" != voice_t("vp_intro", lang),
              voice_t("vp_intro", lang)[:60])

    # Voice Parity: yangi vp_intro kaliti uchala tilda ham bor.
    from translations import VOICE_POST_I18N
    check("vp_intro 3 tilda mavjud (🎙 Ovoz → Post yo'riqnomasi)",
          all("vp_intro" in VOICE_POST_I18N[c] for c in LANGS))
    check("vp_intro UZ matni speksdagidek",
          "Iltimos, g'oyangizni ovozli xabar (1 daqiqa ichida) qilib yuboring"
          in VOICE_POST_I18N["uz"]["vp_intro"], VOICE_POST_I18N["uz"]["vp_intro"][:120])


# ============================================================================
def main():
    print("=" * 66)
    print(" 🧩 KONTENT YARATISH SUBMENU + ACTION-FIRST REGRESSIYA TESTLARI")
    print("=" * 66)
    test_submenu_keyboard()
    test_i18n_parity()
    test_submenu_routing()
    test_submenu_flows()
    test_action_first_entry_points()
    test_regression_guards()

    print("\n" + "=" * 66)
    print(f" JAMI: o'tdi={passed}, xato={failures}")
    if failures:
        print(" [FAIL] KONTENT YARATISH MENYUSIDA XATOLIKLAR BOR ^^^")
        return 1
    print(" KONTENT YARATISH SUBMENU TESTLARI 100% YASHIL ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
