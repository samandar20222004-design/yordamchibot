#!/usr/bin/env python3
"""🧩 BIRLASHTIRILGAN KONTENT YARATISH MENYUSI + ACTION-FIRST regressiyasi.

DIQQAT: BOTNI ODDIY (AI'SIZ) POSTINGGA MOSLASH — menyu bo'lingan va chalkash
5 tugmadan 3 ta mantiqiy yo'nalishga birlashtirildi:

  TEST 1:  [✨ Kontent yaratish] bosilganda ICHKI MENYUDA aynan 3 ta
           yo'nalish + ◀️ Orqaga bo'ladi va qatorlar speksdagi tartibda:
               [✍️ Oddiy post (AI'siz)]
               [✨ AI bilan yaratish (Magic Post)]
               [🤖 AI Yordamchi]
                   [◀️ Orqaga]
  TEST 2:  PARITY — barcha tugmalar UZ / RU / EN tillarida to'liq sinxron
           (registry + klaviatura + parity hisobotlari).
  TEST 3:  ROUTING — har bir submenu tugmasi REAL router'da o'z oqimini
           ochadi: ✍️ → manual_post_entry (AI'siz), ✨ → magic_post_entry,
           🤖 → ai_studio_hub_entry, ◀️ → content_creation_back. ESKI
           yorliqlar (📝 Matn → Post, 🎙 Ovoz → Post, 🤖 AI Yordamchi,
           📸 Rasm → Post, ✨ Magic Post) routing ALIAS'i sifatida ishlaydi.
  TEST 4:  OQIMLAR — har bir tugma bosilganda handler XATOSIZ ishlaydi;
           ✍️ Oddiy post oqimi HECH QANDAY AI savol/uslub ekranini ochmaydi.
  TEST 5:  ACTION-FIRST — menyu tashqarisida ovoz → STT oqimi, rasm → Vision
           oqimi, xom matn → «✨ Magic Post» taklifi (qisqa matn eski javob);
           «mnp_» stale entry dialog ichida holatni buzmaydi.
  TEST 6:  REGRESSIYA QO'RIQONLARI — asosiy menyu 7 tugma (3-QISM),
           fallback ENG oxirgi handler, yangi holat/prefikslar unikal,
           eski handlerlar ro'yxati buzilmagan, hardcode matn yo'q.

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

# Speksdagi QAT'IY BIRLASHTIRILGAN layout (uchala tilda bir xil tartib,
# yorliqlar tarjima qilinadi).
EXPECTED_SUBMENU = {
    "uz": [["✍️ Oddiy post (AI'siz)"],
           ["✨ AI bilan yaratish (Magic Post)"],
           ["🤖 AI Yordamchi"],
           ["◀️ Orqaga"]],
    "ru": [["✍️ Обычный пост (без AI)"],
           ["✨ Создать с AI (Magic Post)"],
           ["🤖 AI Помощник"],
           ["◀️ Назад"]],
    "en": [["✍️ Regular post (no AI)"],
           ["✨ Create with AI (Magic Post)"],
           ["🤖 AI Assistant"],
           ["◀️ Back"]],
}

# Har bir submenu tugmasi ochishi KERAK BO'LGAN oqim handleri.
EXPECTED_ROUTE = {
    "cm_btn_manual": "manual_post_entry",
    "cm_btn_magic": "magic_post_entry",
    "cm_btn_studio": "ai_studio_hub_entry",
    "cm_btn_back": "content_creation_back",
}

# Menyudan olib tashlangan ESKI yorliqlar — routing ALIAS'i sifatida
# saqlanadi (chat tarixidagi eski klaviatura xabarlari buzilmaydi).
LEGACY_ROUTE = {
    "cm_btn_text": "manual_post_entry",      # 📝 Matn → Post → Oddiy post
    "cm_btn_image": "image_post_entry",      # 📸 Rasm → Post (Vision)
    "cm_btn_voice": "voice_post_entry",      # 🎙 Ovoz → Post (STT)
    "cm_btn_ai": "ai_studio_hub_entry",      # eski 🤖 AI Yordamchi aliasi
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
import handlers.manual_post as MP_MOD  # noqa: E402
from handlers.manual_post import (  # noqa: E402
    MANUAL_AWAIT_CONTENT, MANUAL_CHANNEL_SELECT, MANUAL_EDIT_INPUT,
    MANUAL_PREVIEW, MANUAL_TIME_INPUT, ManualEntryHandler, manual_post_entry,
)
from handlers.new_post import CHOOSE_CHANNEL  # noqa: E402
from handlers.voice_post import (  # noqa: E402
    VOICE_AWAIT, VoiceEntryHandler, voice_post_entry,
)
from keyboards.default import (  # noqa: E402
    BTN_ADMIN_PANEL, MENU_TEXTS, get_content_creation_keyboard,
    get_main_keyboard, is_menu_text,
)
from locales.translations import get_text  # noqa: E402
from translations import (  # noqa: E402
    CONTENT_MENU_I18N, CONTENT_MENU_KEYS, content_menu_parity_report,
    content_menu_t, magic_post_parity_report, voice_post_parity_report,
    voice_t,
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

    async def reply_photo(self, photo=None, **kwargs):
        self.sent.append(dict(photo=photo, **kwargs))
        return SimpleNamespace(message_id=2, chat=SimpleNamespace(id=self.chat_id))

    async def reply_video(self, video=None, **kwargs):
        self.sent.append(dict(video=video, **kwargs))
        return SimpleNamespace(message_id=3, chat=SimpleNamespace(id=self.chat_id))

    async def reply_document(self, document=None, **kwargs):
        self.sent.append(dict(document=document, **kwargs))
        return SimpleNamespace(message_id=4, chat=SimpleNamespace(id=self.chat_id))

    async def reply_animation(self, animation=None, **kwargs):
        self.sent.append(dict(animation=animation, **kwargs))
        return SimpleNamespace(message_id=5, chat=SimpleNamespace(id=self.chat_id))

    async def _noop(self, *a, **kw):
        return None


class _Query:
    def __init__(self, data, message):
        self.data = data
        self.message = message
        self.from_user = message.from_user
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
    """Haqiqiy PTB Application + register_all_handlers (tarmoqqa chiqmaydi)."""
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
# TEST 1 — BIRLASHTIRILGAN SUBMENU: 3 yo'nalish + ◀️ Orqaga
# ============================================================================
def test_submenu_keyboard():
    print("\n== TEST 1: [✨ Kontent yaratish] ichki menyusi — birlashtirilgan ==")
    for lang in LANGS:
        kb = get_content_creation_keyboard(lang)
        rows = kb_rows(kb)
        check(f"submenu[{lang}]: qatorlar speksdagidek",
              rows == EXPECTED_SUBMENU[lang], str(rows))
        check(f"submenu[{lang}]: 3 yo'nalish + Orqaga = 4",
              len(kb_flat(kb)) == 4, str(kb_flat(kb)))
        check(f"submenu[{lang}]: takror yo'q",
              len(set(kb_flat(kb))) == 4, str(kb_flat(kb)))
        check(f"submenu[{lang}]: resize_keyboard=True (pastki klaviatura)",
              kb.resize_keyboard is True)
        check(f"submenu[{lang}]: 1-qator ✍️ Oddiy post (AI'siz)",
              rows[0] == [content_menu_t("cm_btn_manual", lang)])
        check(f"submenu[{lang}]: 2-qator ✨ AI bilan yaratish (Magic Post)",
              rows[1] == [content_menu_t("cm_btn_magic", lang)])
        check(f"submenu[{lang}]: 3-qator 🤖 AI Yordamchi",
              rows[2] == [content_menu_t("cm_btn_studio", lang)])
        check(f"submenu[{lang}]: 4-qator ◀️ Orqaga",
              rows[3] == [content_menu_t("cm_btn_back", lang)])

    # ESKI bo'lingan tugmalar (Matn/Rasm/Ovoz → Post) endi ko'rinadigan
    # menyuda YO'Q — ular faqat routing alias'i. ESKI «🤖 AI Yordamchi»
    # yorlig'i esa 3-QISMda ataylab QAYTA ishlatildi (AI Studio → AI
    # Yordamchi nomi qaytdi), shuning uchun uning uz/en qiymatlari yangi
    # ko'rinadigan tugma bilan AYNAN bir xil — bu dublikat EMAS.
    visible_now = {
        content_menu_t(key, lang)
        for key in ("cm_btn_manual", "cm_btn_magic", "cm_btn_studio", "cm_btn_back")
        for lang in LANGS
    }
    legacy_labels = {
        content_menu_t(key, lang)
        for key in ("cm_btn_text", "cm_btn_image", "cm_btn_voice", "cm_btn_ai")
        for lang in LANGS
    } - visible_now
    for lang in LANGS:
        visible = set(kb_flat(get_content_creation_keyboard(lang)))
        leaked = visible & legacy_labels
        check(f"submenu[{lang}]: eski bo'lingan tugmalar menyuda YO'Q",
              not leaked, str(leaked))

    # Asosiy menyu 7 tugma STANDARTI (submenu unga aralashmaydi).
    for lang in LANGS:
        main_flat = kb_flat(get_main_keyboard(False, lang=lang))
        check(f"main[{lang}]: 7 tugma saqlangan", len(main_flat) == 7, str(main_flat))
        check(f"main[{lang}]: submenu tugmalari asosiy menyuda YO'Q",
              not set(main_flat) & set(kb_flat(get_content_creation_keyboard(lang))))
    check("main[admin]: 8 tugma (Admin Panel oxirgi qatorda)",
          kb_rows(get_main_keyboard(True, lang="uz"))[-1] == [BTN_ADMIN_PANEL])


# ============================================================================
# TEST 2 — UZ / RU / EN PARITY (to'liq sinxron)
# ============================================================================
def test_i18n_parity():
    print("\n== TEST 2: UZ/RU/EN paritet — birlashtirilgan menyu lug'ati ==")
    report = content_menu_parity_report()
    check("content_menu pariteti in_sync", report["in_sync"] is True, str(report))
    check("CONTENT_MENU_KEYS lug'at bilan bir xil",
          set(CONTENT_MENU_KEYS) == set(CONTENT_MENU_I18N["uz"]), "")

    # Har bir tugma yorlig'i uchala tilda mavjud va bo'sh emas.
    visible_keys = ("cm_btn_manual", "cm_btn_magic", "cm_btn_studio", "cm_btn_back")
    for key in visible_keys:
        vals = [CONTENT_MENU_I18N[c][key] for c in LANGS]
        check(f"{key}: 3 tilda ham to'liq", all(v and v.strip() for v in vals), str(vals))
        check(f"{key}: kalit tugma klaviaturasiga kiradi",
              all(v in kb_flat(get_content_creation_keyboard(c))
                  for c, v in zip(LANGS, vals)), str(vals))
    # 3-QISM: «AI Studio» → «AI Yordamchi» — endi UCHALA TILDA tarjima
    # qilinadi (🤖 AI Yordamchi / 🤖 AI Помощник / 🤖 AI Assistant).
    check("cm_btn_studio: 3 tilda tarjima (AI Yordamchi)",
          {CONTENT_MENU_I18N[c]["cm_btn_studio"] for c in LANGS} ==
          {"🤖 AI Yordamchi", "🤖 AI Помощник", "🤖 AI Assistant"},
          str({CONTENT_MENU_I18N[c]["cm_btn_studio"] for c in LANGS}))
    check("cm_btn_studio: 'Studio' so'zi qolmadi",
          all("Studio" not in CONTENT_MENU_I18N[c]["cm_btn_studio"] for c in LANGS))
    for key in ("cm_btn_manual", "cm_btn_magic", "cm_btn_back"):
        vals = {CONTENT_MENU_I18N[c][key] for c in LANGS}
        check(f"{key}: 3 tilda farqli (sinxron tarjima)", len(vals) == 3, str(vals))

    # ESKI yorliqlar lug'atda SAQLANADI (routing alias manbasi).
    # cm_btn_ai (eski «🤖 AI Yordamchi») 3-QISMda yangi nom bilan
    # ataylib birlashtirildi — uning uz/en qiymatlari ko'rinadigan
    # tugmaga AYNAN teng, shuning uchun «CHIZILMAYDI» tekshiruvi
    # faqat haqiqiy alohida aliaslarga qo'llaniladi.
    legacy_keys = ("cm_btn_text", "cm_btn_image", "cm_btn_voice")
    for key in legacy_keys:
        check(f"{key}: alias lug'atda saqlangan (3 til)",
              all(CONTENT_MENU_I18N[c].get(key) for c in LANGS), key)
        check(f"{key}: alias menyuda CHIZILMAYDI",
              all(CONTENT_MENU_I18N[c][key] not in kb_flat(get_content_creation_keyboard(c))
                  for c in LANGS), key)
    check("cm_btn_ai: alias lug'atda saqlangan (3 til)",
          all(CONTENT_MENU_I18N[c].get("cm_btn_ai") for c in LANGS), "cm_btn_ai")

    # MENU_TEXTS registry: yangi oilalar uchala tilda to'liq.
    fams = {
        "content_manual_post": {
            "✍️ Oddiy post (AI'siz)", "✍️ Обычный пост (без AI)",
            "✍️ Regular post (no AI)",
            # eski «📝 Matn → Post» oilasi shu yerga ko'chirildi
            "📝 Matn → Post", "📝 Текст → Пост", "📝 Text → Post",
        },
        "content_studio": {
            "🤖 AI Studio",  # eski submenu yorlig'i (routing alias)
            "🤖 AI Yordamchi", "🤖 AI Помощник", "🤖 AI Assistant",
            "🤖 AI-помощник",
        },
        "content_voice_post": {"🎙 Ovoz → Post", "🎙 Голос → Пост", "🎙 Voice → Post"},
        "content_back": {"◀️ Orqaga", "◀️ Назад", "◀️ Back"},
    }
    for action, expected in fams.items():
        check(f"MENU_TEXTS['{action}'] uchala til + aliaslarni o'z ichiga oladi",
              expected <= set(MENU_TEXTS.get(action, ())), str(MENU_TEXTS.get(action)))
    # Magic oilasi: eski brend va yangi submenu yorlig'i BITTA oilada.
    magic_fam = set(MENU_TEXTS.get("magic_post", ()))
    for label in ("✨ Magic Post", "✨ AI bilan yaratish (Magic Post)",
                  "✨ Создать с AI (Magic Post)", "✨ Create with AI (Magic Post)"):
        check(f"magic_post oilasida {label!r} bor", label in magic_fam, str(sorted(magic_fam)))

    # is_menu_text: har bir ko'rinadigan tugma o'z oilasida taniladi.
    for lang in LANGS:
        check(f"is_menu_text[{lang}] manual → content_manual_post",
              is_menu_text(content_menu_t("cm_btn_manual", lang), "content_manual_post"))
        check(f"is_menu_text[{lang}] studio → content_studio",
              is_menu_text(content_menu_t("cm_btn_studio", lang), "content_studio"))
        check(f"is_menu_text[{lang}] eski Matn → Post → content_manual_post",
              is_menu_text(content_menu_t("cm_btn_text", lang), "content_manual_post"))
        check(f"is_menu_text[{lang}] eski AI Yordamchi → content_studio",
              is_menu_text(content_menu_t("cm_btn_ai", lang), "content_studio"))

    # Qo'shni lug'atlar ham buzilmagan (paritet hisobotlari).
    check("voice_post pariteti in_sync", voice_post_parity_report()["in_sync"] is True, "")
    check("magic_post pariteti in_sync", magic_post_parity_report()["in_sync"] is True, "")


# ============================================================================
# TEST 3 — ROUTING: har bir tugma o'z oqimini ochadi (real router)
# ============================================================================
def test_submenu_routing():
    print("\n== TEST 3: routing — birlashtirilgan menyu tugmalari real router'da ==")
    _app, conv, regex = _conv_and_regex_handlers()

    for key, expected in EXPECTED_ROUTE.items():
        for lang in LANGS:
            label = content_menu_t(key, lang)
            names = _targets(regex, label)
            check(f"[{lang}] {label!r} → {expected}", names == {expected}, str(sorted(names)))

    # ESKI yorliqlar — routing ALIAS'i (chat tarixidagi tugmalar buzilmaydi).
    for key, expected in LEGACY_ROUTE.items():
        for lang in LANGS:
            label = content_menu_t(key, lang)
            names = _targets(regex, label)
            check(f"[{lang}] eski {label!r} → {expected} (alias)",
                  names == {expected}, str(sorted(names)))

    # «✨ Kontent yaratish» (va meros «✨ AI Studio» asosiy menyu yorlig'i)
    # submenu'ni ochadi.
    for lang in LANGS:
        for key in ("btn_create_content",):
            label = get_text(key, lang)
            names = _targets(regex, label)
            check(f"[{lang}] {label!r} → ai_studio_menu_entry (submenu)",
                  names == {"ai_studio_menu_entry"}, str(sorted(names)))
    for label in ("✨ AI Studio", "✨ AI Студия", "✨ Studio"):
        names = _targets(regex, label)
        check(f"eski asosiy menyu {label!r} → ai_studio_menu_entry (alias)",
              names == {"ai_studio_menu_entry"}, str(sorted(names)))

    # «🤖 AI Yordamchi» (eski «🤖 AI Studio» submenu yorlig'i) AI
    # Yordamchi HUB'iga boradi (asosiy menyu entry'siga EMAS).
    for label in ("🤖 AI Studio", "🤖 AI Yordamchi", "🤖 AI Помощник",
                  "🤖 AI Assistant", "🤖 AI-помощник"):
        names = _targets(regex, label)
        check(f"{label!r} faqat ai_studio_hub_entry ga boradi",
              names == {"ai_studio_hub_entry"}, str(sorted(names)))

    # Hech bir submenu tugmasi fallback'ga tushmaydi.
    for key in list(EXPECTED_ROUTE) + list(LEGACY_ROUTE):
        for lang in LANGS:
            label = content_menu_t(key, lang)
            names = _targets(regex, label)
            check(f"[{lang}] {label!r} fallback EMAS",
                  bool(names) and "unknown_message_fallback" not in names, str(sorted(names)))

    # Dialog ICHIDA ham submenu tugmalari ishlaydi (all_menu_jumps parity).
    for state in (MAGIC_INPUT, IMAGE_POST_INPUT, CHOOSE_CHANNEL, VOICE_AWAIT,
                  AI_MENU_STATE, MANUAL_AWAIT_CONTENT, MANUAL_PREVIEW):
        handlers = conv.states[state]
        for key, expected in EXPECTED_ROUTE.items():
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


# ============================================================================
# TEST 4 — OQIMLAR: har bir tugma XATOSIZ ishlaydi
# ============================================================================
def test_submenu_flows():
    print("\n== TEST 4: oqimlar — birlashtirilgan menyu haqiqiy handlerlarni ochadi ==")
    for lang in LANGS:
        # 1) [✨ Kontent yaratish] → birlashtirilgan ichki menyu ochiladi.
        rec = _Rec()
        res = asyncio.run(ai_studio_menu_entry(_update_msg(rec), _ctx(lang)))
        sent = rec.sent
        check(f"[{lang}] ✨ Kontent yaratish → submenu chiqdi", len(sent) == 1, str(sent))
        check(f"[{lang}] submenu klaviaturasi aniq 3+1 tugma",
              sent and kb_rows(sent[0]["reply_markup"]) == EXPECTED_SUBMENU[lang],
              str(kb_rows(sent[0]["reply_markup"]) if sent else None))
        check(f"[{lang}] submenu dialog OCHMAYDI (action-first saqlanadi)",
              res == ConversationHandler.END, str(res))

        # 2) [✍️ Oddiy post (AI'siz)] — AI savollarisiz kontent kutish.
        restore = _patch_db({"get_user_channels": [("-100123", "Asosiy kanal")]})
        try:
            rec = _Rec()
            res = asyncio.run(manual_post_entry(_update_msg(rec), _ctx(lang)))
            check(f"[{lang}] ✍️ Oddiy post → MANUAL_AWAIT_CONTENT holati",
                  res == MANUAL_AWAIT_CONTENT, str(res))
            text = rec.sent[0]["text"] if rec.sent else ""
            check(f"[{lang}] ✍️ Oddiy post yo'riqnomasi chiqdi", bool(text), text[:80])
            check(f"[{lang}] ✍️ Oddiy post: HECH QANDAY AI uslub savoli YO'Q",
                  rec.sent and "reply_markup" in rec.sent[0]
                  and not hasattr(rec.sent[0]["reply_markup"], "inline_keyboard"),
                  str(rec.sent)[:120])
        finally:
            restore()

        # 2b) ✍️ kanal ulanmagan bo'lsa — muloyim yo'riqnoma + END.
        restore = _patch_db({"get_user_channels": []})
        try:
            rec = _Rec()
            res = asyncio.run(manual_post_entry(_update_msg(rec), _ctx(lang)))
            check(f"[{lang}] ✍️ kanalsiz → oqim ochilmaydi (END)",
                  res == ConversationHandler.END, str(res))
        finally:
            restore()

        # 3) [✨ AI bilan yaratish (Magic Post)] → Magic Post FSM.
        rec = _Rec()
        res = asyncio.run(magic_post_entry(_update_msg(rec), _ctx(lang)))
        check(f"[{lang}] ✨ AI bilan yaratish → MAGIC_INPUT holati",
              res == MAGIC_INPUT, str(res))
        check(f"[{lang}] ✨ AI bilan yaratish yo'riqnomasi chiqdi",
              len(rec.sent) == 1 and rec.sent[0]["text"], str(rec.sent))

        # 4) [🤖 AI Yordamchi] → audit/tahlil vositalari bo'limi.
        restore = _patch_db({"is_premium": False, "get_user_credits": 7})
        try:
            rec = _Rec()
            res = asyncio.run(ai_studio_hub_entry(_update_msg(rec), _ctx(lang)))
            check(f"[{lang}] 🤖 AI Yordamchi → AI bo'limi ochildi",
                  res == AI_MENU_STATE and len(rec.sent) == 1, f"{res} {rec.sent}")
            labels = [b.text for row in rec.sent[0]["reply_markup"].inline_keyboard for b in row]
            check(f"[{lang}] AI bo'limida audit vositasi bor",
                  any("audit" in lb.lower() or "Audit" in lb or "аудит" in lb.lower()
                      for lb in labels), str(labels))
        finally:
            restore()

        # 5) [◀️ Orqaga] → asosiy 7 tugmali menyu.
        rec = _Rec()
        res = asyncio.run(content_creation_back(_update_msg(rec), _ctx(lang)))
        check(f"[{lang}] ◀️ Orqaga → asosiy 7 tugmali menyu",
              rec.sent and kb_flat(rec.sent[0]["reply_markup"]) ==
              kb_flat(get_main_keyboard(False, lang=lang)), str(rec.sent))
        check(f"[{lang}] ◀️ Orqaga → dialog yopildi (END)",
              res == ConversationHandler.END, str(res))

        # 6) ESKI aliaslar ham o'z oqimini ochadi (backward compatibility).
        rec = _Rec()
        res = asyncio.run(voice_post_entry(_update_msg(rec), _ctx(lang)))
        check(f"[{lang}] 🎙 Ovoz → Post alias → VOICE_AWAIT", res == VOICE_AWAIT, str(res))
        rec = _Rec()
        res = asyncio.run(image_post_entry(_update_msg(rec), _ctx(lang)))
        check(f"[{lang}] 📸 Rasm → Post alias → IMAGE_POST_INPUT",
              res == IMAGE_POST_INPUT, str(res))


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
    manual_entry = [h for h in entry_points if isinstance(h, ManualEntryHandler)]
    check("VoiceEntryHandler main_conv entry point'ida", len(voice_entry) == 1)
    check("ImageEntryHandler main_conv entry point'ida", len(image_entry) == 1)
    check("ContentOfferEntryHandler (cc_) main_conv entry point'ida",
          len(offer_entry) == 1 and offer_entry[0].pattern.pattern == "^cc_",
          str([getattr(h, "pattern", None) for h in offer_entry]))
    check("ManualEntryHandler (mnp_) main_conv entry point'ida",
          len(manual_entry) == 1 and manual_entry[0].pattern.pattern == "^mnp_",
          str([getattr(h, "pattern", None) for h in manual_entry]))

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
        if manual_entry:
            check("dialog ichida mnp_ tugmasi mos KELMAYDI (holat buzilmaydi)",
                  not manual_entry[0].check_update(_callback_update("mnp_now")))
    finally:
        conv._conversations.pop(key, None)
    if offer_entry:
        check("dialog tashqarisida cc_magic → mos keladi",
              bool(offer_entry[0].check_update(_callback_update(CC_MAGIC))))
    if manual_entry:
        check("dialog tashqarisida mnp_now → stale entry mos keladi",
              bool(manual_entry[0].check_update(_callback_update("mnp_now"))))

    # --- XOM MATN → Magic Post taklifi ---
    material = ("Samarqanddagi yangi kofeyamiz uchun post yozib ber: "
                "uchinchi aprel kuni ochilamiz, birinchi mijozlarga chegirma")
    check("gate: uzun matn material hisoblanadi", looks_like_post_material(material))
    check("gate: qisqa matn material EMAS", not looks_like_post_material("???"))
    check("gate: /command material EMAS", not looks_like_post_material("/start " + "x" * 60))

    for lang, expected in (("uz", get_text("unknown_message_fallback", "uz")),
                          ("ru", get_text("unknown_message_fallback", "ru"))):
        # a) Qisqa matn → eski xushmuomala javob + asosiy menyu (o'zgarmagan).
        H._UNKNOWN_FALLBACK_LAST.clear()
        rec = _Rec(text="???")
        asyncio.run(H.unknown_message_fallback(_update_msg(rec), _ctx(lang)))
        check(f"[{lang}] qisqa matn → eski fallback matni + asosiy menyu",
              len(rec.sent) == 1 and rec.sent[0]["text"] == expected,
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

        # c) Taklifni bosish → Magic Post uslub tanlash ekrani (matn yo'qolmaydi).
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

        # d) cc_menu → asosiy menyu + END
        query2 = _Query(CC_MENU, _Rec())
        res2 = asyncio.run(content_offer_callback(_update_query(query2), _ctx(lang)))
        check(f"[{lang}] cc_menu → asosiy menyuga qaytish (END)",
              res2 == ConversationHandler.END
              and kb_flat(query2.message.sent[0]["reply_markup"]) ==
              kb_flat(get_main_keyboard(False, lang=lang)), str(res2))

    # TTL: 20 daqiqadan eskirgan matn ishlatilmaydi.
    CC_MOD._DIRECT_TEXT.clear()
    remember_direct_text(9911, "eski matn " * 10)
    CC_MOD._DIRECT_TEXT[9911] = ("eski matn " * 10, time.time() - 3600)
    check("TTL: eskirgan xom matn olinmaydi", take_direct_text(9911) == "")
    CC_MOD._DIRECT_TEXT.clear()


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
    check("post_score_handlers all_menu_jumps ichida", "post_score_handlers +" in body)
    check("birlashtirilgan submenu guruhi all_menu_jumps ichida",
          "content_creation_handlers +" in body)
    check("voice entry point himoyasi saqlangan",
          "VoiceEntryHandler(VOICE_MESSAGE_FILTER, voice_message_received)" in body)
    check("image entry point himoyasi saqlangan",
          "ImageEntryHandler(filters.PHOTO & filters.ChatType.PRIVATE, image_photo_received)" in body)

    # ✍️ Oddiy post FSM holatlari mavjud holatlar bilan TO'QNASHMAYDI.
    import handlers.ai_assistant as ai
    import handlers.image_post as ip
    import handlers.magic_post as mp
    import handlers.new_post as np_mod
    import handlers.post_score as ps
    import handlers.voice_post as vp
    manual_states = {MP_MOD.MANUAL_AWAIT_CONTENT, MP_MOD.MANUAL_PREVIEW,
                     MP_MOD.MANUAL_CHANNEL_SELECT, MP_MOD.MANUAL_TIME_INPUT,
                     MP_MOD.MANUAL_EDIT_INPUT}
    other_states = (
        {mp.MAGIC_INPUT, mp.MAGIC_STYLE_SELECT, mp.MAGIC_RESULT, mp.MAGIC_SEND_CHOOSE}
        | {vp.VOICE_AWAIT, vp.VOICE_STYLE_SELECT, vp.VOICE_RESULT, vp.VOICE_SEND_CHOOSE}
        | {ip.IMAGE_POST_INPUT, ip.IMAGE_STYLE_SELECT, ip.IMAGE_POST_RESULT,
           ip.IMAGE_SEND_CHOOSE, ip.IMAGE_SCHEDULE_INPUT}
        | {ps.POST_SCORE_INPUT, ps.POST_SCORE_RESULT, ps.POST_SCORE_SEND_CHOOSE}
        | {ai.AI_INPUT, ai.AI_CONFIRM, ai.AI_GET_TIME, ai.AI_MENU_STATE,
           ai.AI_PROMPT_INPUT, ai.AI_TONE_SELECT, ai.AI_AUDIT_INPUT}
        | {np_mod.CHOOSE_CHANNEL, np_mod.GET_CONTENT, np_mod.GET_TIME,
           np_mod.CONFIRM_POST}
    )
    check("manual FSM holatlari (450–454) noyob",
          not (manual_states & other_states),
          str(sorted(manual_states & other_states)))
    check("manual FSM holatlari qiymatlari aniq",
          manual_states == {450, 451, 452, 453, 454}, str(sorted(manual_states)))

    app = _build_app()
    all_h = _all_handlers(app)
    conv = [h for h in all_h if isinstance(h, ConversationHandler)][0]
    # Prefiks to'qnashuvi: «mnp_» global stale-handler pattern'lari bilan
    # mos kelmasligi kerak (mp_ Magic Post, vp_, image_, ps_, cc_ ...).
    import re as _re
    stale_patterns = [h.pattern.pattern for h in all_h
                      if isinstance(h, CallbackQueryHandler) and getattr(h, "pattern", None)
                      and not isinstance(h, ManualEntryHandler)]
    check("«mnp_now» boshqa stale-handler pattern'lariga tushmaydi",
          not [pat for pat in stale_patterns if _re.search(pat, "mnp_now")],
          str(stale_patterns))
    check("manual FSM holatlari conv.states'da ro'yxatdan o'tgan",
          all(st in conv.states for st in manual_states), str(sorted(conv.states)))
    check("manual holatlarda panel callback handleri bor",
          any(isinstance(h, CallbackQueryHandler) for h in conv.states[MANUAL_PREVIEW]))

    # App'da fallback ro'yxatdan keyin boshqa handler qo'shilmagan.
    check("oxirgi ro'yxatdan o'tgan handler — fallback",
          getattr(all_h[-1], "callback", None) is H.unknown_message_fallback,
          str(all_h[-1]))
    check("VoiceEntryHandler va ImageEntryHandler hali ham entry point",
          any(isinstance(h, VoiceEntryHandler) for h in conv.entry_points)
          and any(isinstance(h, ImageEntryHandler) for h in conv.entry_points))
    check("allow_reentry saqlangan (entry point'lar dialogda ham tekshiriladi)",
          conv.allow_reentry is True)
    check("conversation timeout o'zgarmagan", conv.conversation_timeout == 600)

    # Asosiy 7 tugma + reply klaviatura API'lari buzilmagan.
    for lang in LANGS:
        check(f"get_main_keyboard[{lang}]: 7 tugma",
              len(kb_flat(get_main_keyboard(False, lang=lang))) == 7)

    # Callback data 64-bayt chegarasida (mnp_ch:<id> eng uzuni).
    from keyboards.callback_data import CALLBACK_DATA_MAX_BYTES, callback_byte_len
    from keyboards.inline import manual_channel_callback
    worst = manual_channel_callback("-1009876543210987")
    check(f"eng uzun mnp callback <= 64 bayt ({worst!r})",
          callback_byte_len(worst) <= CALLBACK_DATA_MAX_BYTES, worst)


# ============================================================================
def main():
    print("=" * 66)
    print(" 🧩 BIRLASHTIRILGAN KONTENT MENYUSI + ACTION-FIRST TESTLARI")
    print("=" * 66)
    test_submenu_keyboard()
    test_i18n_parity()
    test_submenu_routing()
    test_submenu_flows()
    test_action_first_entry_points()
    test_regression_guards()
    print("\n" + "=" * 66)
    print(f" JAMI: o'tdi={passed}, xato={failures}")
    if failures == 0:
        print(" BIRLASHTIRILGAN MENYU TESTLARI 100% YASHIL ✔")
    print("=" * 66)
    return failures == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
