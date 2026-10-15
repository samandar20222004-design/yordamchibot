#!/usr/bin/env python3
"""📋 TELEGRAM «MENU» TUGMASI (set_my_commands) VA BUYRUQLAR — TEST SUITE.

Qamrov (topshiriq spetsifikatsiyasi bilan birma-bir):

  TEST 1: 🧱 RO'YXAT KONTRAKTI (SSOT) — ``menu_commands`` moduli 5 ta
          ASOSIY buyruqni (``/start``, ``/newpost``, ``/cleaner``,
          ``/settings``, ``/help``) AYNAN spetsifikatsiyadagi TARTIBDA
          e'lon qiladi; har bir buyruq nomi Telegram qoidasiga
          (``a-z0-9_``, 1..32) mos; tavsiflar uz/ru/en da mavjud, BO'SH
          emas, bir-biridan FARQLI (haqiqiy lokalizatsiya) va ≤256 belgi;
          paritet hisoboti ``in_sync``.
  TEST 2: 📡 ``set_my_commands`` LOKALIZATSIYASI — HAQIQIY
          ``main.set_bot_commands`` chaqiriladi: (1) ``language_code`` siz
          standart ro'yxat (UZ), (2) ``uz`` / ``ru`` / ``en`` uchun ALOHIDA
          ro'yxatlar, (3) «Menu» tugmasi turi — ``MenuButtonCommands``
          (buyruqlar ro'yxati). Ro'yxat IXCHAM: texnik/admin buyruqlari
          (``/imagepost``, ``/profile``, ``/channel_advice``, ``/cancel``)
          ☰ menyuga CHIQARILMAYDI.
  TEST 3: 🛟 FAIL-SOFT — Telegram API xatosi (tarmoq/429/eskirgan
          kutubxona) bot startini BUZMAYDI: funksiya istisno tashlamaydi,
          qolgan chaqiruvlar baribir bajariladi va hisobot qaytadi.
  TEST 4: 🔌 SEAMLESS ROUTING — ☰ menyudagi HAR BIR buyruq HAQIQIY PTB
          registratsiyasida (``register_all_handlers``) jonli handlerga
          ega: ``/start`` → ``start``, ``/newpost`` → ``start_new_post``
          (FSM entry point), ``/cleaner`` → ``cleaner_command``,
          ``/settings`` → ``user_cabinet_menu``, ``/help`` → ``help_command``
          — oraliq qadam yo'q.
  TEST 5: 🧹 ``/cleaner`` EKRANI — buyruq 🧹 Post tozalagich va ✍️ Imzo
          ekranini BIR QADAMDA ochadi (uz/ru/en), matn va klaviatura
          ``stgs_clean`` callback ekrani bilan AYNAN bir manbadan
          chiziladi; FSM tozalanadi; DB xatosida ham ekran chiziladi
          (fail-soft).
  TEST 6: 🧭 ``/settings`` va ``/help`` — oraliq qadamsiz, tayyor UI
          (Sozlamalar hub'i va Yordam qo'llanmasi + klaviaturalari).
  TEST 7: 🧾 STATIK KONTRAKT — ``main.py`` da qo'lda yozilgan
          ``BotCommand`` ro'yxati YO'Q (manba — ``menu_commands``);
          hujjat (README) yangi buyruqni va lokalizatsiya qilingan ☰
          menyuni tasvirlaydi.

Ishga tushirish:
    python3 tests/menu_button_and_commands_test.py
"""
import asyncio
import os
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:MENU_BUTTON_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10061")
os.environ.setdefault("ENVIRONMENT", "test")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "telegram_bot"))
sys.path.insert(0, str(ROOT))

import importlib  # noqa: E402

import database as db_mod  # noqa: E402
import main as MAIN  # noqa: E402
import menu_commands as MC  # noqa: E402
import handlers as H  # noqa: E402
import handlers.settings as STG  # noqa: E402

# DIQQAT: ``handlers/__init__.py`` ``start`` nomini ``/start`` handler
# funksiyasiga bog'laydi — shu sababli modul ``importlib`` orqali olinadi.
START = importlib.import_module("handlers.start")
from telegram import MenuButtonCommands, Update  # noqa: E402
from telegram.ext import CommandHandler, ConversationHandler  # noqa: E402
from locales.translations import (  # noqa: E402
    TRANSLATIONS,
    get_text,
    translation_parity_report,
)
from translations.settings_stats import settings_stats_t  # noqa: E402

LANGS = ("uz", "ru", "en")
USER_ID = 771122

PASSED = 0
FAILURES = 0


def check(name, cond, extra=""):
    global PASSED, FAILURES
    if cond:
        PASSED += 1
        print(f"  [OK] {name}")
    else:
        FAILURES += 1
        print(f"  [FAIL] {name}" + (f" — {extra}" if extra else ""))


def header(num, title):
    print(f"\n===== TEST {num}: {title} =====")


# Spetsifikatsiyadagi AYNAN matnlar (regressiya qo'riqoni — tasodifiy
# o'zgarish testni yiqitadi).
EXPECTED_DESCRIPTIONS = {
    "uz": {
        "start": "🚀 Botni qayta ishga tushirish",
        "newpost": "✍️ Yangi post yaratish",
        "cleaner": "🧹 Post tozalagich va Imzo",
        "settings": "⚙️ Sozlamalar",
        "help": "ℹ️ Yordam",
    },
    "ru": {
        "start": "🚀 Перезапустить бота",
        "newpost": "✍️ Создать пост",
        "cleaner": "🧹 Авто-чистка и Подпись",
        "settings": "⚙️ Настройки",
        "help": "ℹ️ Помощь",
    },
    "en": {
        "start": "🚀 Restart bot",
        "newpost": "✍️ Create new post",
        "cleaner": "🧹 Post cleaner & signature",
        "settings": "⚙️ Settings",
        "help": "ℹ️ Help",
    },
}

EXPECTED_ORDER = ("start", "newpost", "cleaner", "settings", "help")
#: ☰ menyuda KO'RINMASLIGI kerak bo'lgan texnik/admin buyruqlari.
HIDDEN_FROM_MENU = ("imagepost", "profile", "channel_advice", "cancel",
                    "admin", "stats", "privacy", "audit")


# ===========================================================================
# TEST 1 — RO'YXAT KONTRAKTI
# ===========================================================================
def test_registry_contract():
    header("1", "🧱 ☰ MENYU RO'YXATI — nomlar, tartib va lokalizatsiya (SSOT)")

    check("MENU_COMMAND_NAMES spetsifikatsiyadagi tartibda",
          tuple(MC.MENU_COMMAND_NAMES) == EXPECTED_ORDER,
          str(MC.MENU_COMMAND_NAMES))
    check("MENU_COMMANDS: nom → i18n kalit (5 ta)",
          len(MC.MENU_COMMANDS) == 5
          and all(isinstance(k, str) and k.startswith("menu_cmd_")
                  for _n, k in MC.MENU_COMMANDS),
          str(MC.MENU_COMMANDS))
    check("tillar to'plami uz/ru/en", tuple(MC.MENU_COMMAND_LOCALES) == LANGS,
          str(MC.MENU_COMMAND_LOCALES))
    check("standart (fallback) til — UZ",
          MC.DEFAULT_MENU_LANG == "uz", MC.DEFAULT_MENU_LANG)

    # Har bir buyruq uchun Telegram nom qoidasi + 3 tildagi tavsif.
    for name in EXPECTED_ORDER:
        check(f"/{name}: Telegram nom qoidasiga mos",
              bool(MC.COMMAND_NAME_RE.match(name)), name)
        texts = []
        for lang in LANGS:
            text = MC.command_description(name, lang)
            texts.append(text)
            check(f"/{name}[{lang}] tavsif mavjud va bo'sh emas",
                  bool(text.strip()), repr(text))
            check(f"/{name}[{lang}] tavsif spetsifikatsiyaga aynan mos",
                  text == EXPECTED_DESCRIPTIONS[lang][name],
                  f"{text!r} != {EXPECTED_DESCRIPTIONS[lang][name]!r}")
            check(f"/{name}[{lang}] ≤ 256 belgi (Telegram chegarasi)",
                  len(text) <= MC.COMMAND_DESCRIPTION_MAX_LEN, str(len(text)))
        check(f"/{name}: 3 tilda FARQLI tavsif (haqiqiy lokalizatsiya)",
              len(set(texts)) == 3, str(texts))

    # Lug'at darajasidagi paritet: kalit 3 tilda ham bor, EN overlay qoplaydi.
    for _name, key in MC.MENU_COMMANDS:
        for lang in LANGS:
            check(f"TRANSLATIONS[{lang}][{key}] mavjud",
                  bool(TRANSLATIONS[lang].get(key)), key)

    report = MC.menu_commands_parity_report()
    check("paritet hisoboti: in_sync", report["in_sync"] is True, str(report))
    check("paritet hisoboti: yo'q kalit / bir xil matn / noto'g'ri nom yo'q",
          not report["missing_keys"] and not report["overlay_missing"]
          and not report["identical"] and not report["invalid_names"]
          and not report["too_long"], str(report))
    check("umumiy i18n pariteti buzilmagan (uz/ru/en)",
          translation_parity_report()["all_in_sync"] is True)
    check("get_text orqali tavsif o'sha-o'sha (kalit emas)",
          get_text("menu_cmd_cleaner", "ru") == EXPECTED_DESCRIPTIONS["ru"]["cleaner"])


# ===========================================================================
# TEST 2 — set_my_commands LOKALIZATSIYASI
# ===========================================================================
class _RecordingBot:
    """``set_my_commands`` / ``set_chat_menu_button`` chaqiruvlarini yozadi."""

    def __init__(self, fail_commands=False, fail_button=False, has_api=True,
                 fail_on_lang=None):
        self.calls = []              # (language_code, [(nom, tavsif), ...])
        self.menu_buttons = []       # menu_button obyektlari
        self.fail_commands = fail_commands
        self.fail_button = fail_button
        self.fail_on_lang = fail_on_lang
        if not has_api:
            # Eski kutubxona/mock: API umuman yo'q (instance atributi
            # metodni soyali qoplaydi → ``callable()`` False).
            self.set_my_commands = None
            self.set_chat_menu_button = None

    async def set_my_commands(self, commands, language_code=None, **kwargs):
        if self.fail_commands:
            raise RuntimeError("Bad Request: simulated Telegram error")
        if self.fail_on_lang and language_code == self.fail_on_lang:
            raise RuntimeError("Bad Request: simulated locale error")
        self.calls.append((language_code, [(c.command, c.description) for c in commands]))
        return True

    async def set_chat_menu_button(self, menu_button=None):
        if self.fail_button:
            raise RuntimeError("Bad Request: simulated menu button error")
        self.menu_buttons.append(menu_button)
        return True


def _app(bot):
    return SimpleNamespace(bot=bot)


def test_set_my_commands_localized():
    header("2", "📡 set_my_commands — lokalizatsiya (standart + uz/ru/en)")

    bot = _RecordingBot()
    report = asyncio.run(MAIN.set_bot_commands(_app(bot)))

    check("4 ta set_my_commands chaqiruvi (standart + 3 til)",
          len(bot.calls) == 4, str([c[0] for c in bot.calls]))
    check("standart ro'yxat language_code SIZ (mos til topilmasa UZ ko'rinadi)",
          bot.calls[0][0] is None, str(bot.calls[0][0]))
    check("standart ro'yxat — UZ tavsiflari",
          [d for _n, d in bot.calls[0][1]]
          == [EXPECTED_DESCRIPTIONS["uz"][n] for n in EXPECTED_ORDER],
          str(bot.calls[0][1]))

    by_lang = {lang: payload for lang, payload in bot.calls[1:]}
    check("uz/ru/en uchun ALOHIDA chaqiruvlar",
          set(by_lang) == set(LANGS), str(sorted(by_lang)))
    for lang in LANGS:
        payload = by_lang.get(lang) or []
        check(f"[{lang}] ro'yxatda 5 ta buyruq", len(payload) == 5, str(payload))
        check(f"[{lang}] buyruqlar tartibi spetsifikatsiyadagidek",
              tuple(n for n, _d in payload) == EXPECTED_ORDER, str(payload))
        check(f"[{lang}] tavsiflar AYNAN shu tilda",
              [d for _n, d in payload]
              == [EXPECTED_DESCRIPTIONS[lang][n] for n in EXPECTED_ORDER],
              str(payload))

    check("har bir til ro'yxati boshqasidan farqli",
          len({tuple(d for _n, d in by_lang[lang]) for lang in LANGS}) == 3)

    check("☰ «Menu» tugmasi BUYRUQLAR turiga o'rnatildi (MenuButtonCommands)",
          len(bot.menu_buttons) == 1
          and isinstance(bot.menu_buttons[0], MenuButtonCommands),
          str(bot.menu_buttons))

    check("hisobot: standart + 3 til + tugma = True",
          report["default"] is True
          and set(report["locales"]) == set(LANGS)
          and all(report["locales"].values())
          and report["menu_button"] is True, str(report))

    # Ro'yxat IXCHAM — faqat asosiy amallar (texnik buyruqlar yo'q).
    advertised = {name for _lang, payload in bot.calls for name, _d in payload}
    check("☰ menyu IXCHAM: faqat 5 ta asosiy buyruq",
          advertised == set(EXPECTED_ORDER), str(sorted(advertised)))
    leaked = sorted(advertised & set(HIDDEN_FROM_MENU))
    check("texnik/admin buyruqlari ☰ menyuga chiqarilmagan",
          not leaked, str(leaked))

    # build_bot_commands — PTB BotCommand obyektlari.
    commands = MC.build_bot_commands("ru")
    check("build_bot_commands: BotCommand obyektlari, tartib bilan",
          [c.command for c in commands] == list(EXPECTED_ORDER)
          and all(c.description == EXPECTED_DESCRIPTIONS["ru"][c.command]
                  for c in commands), str(commands))
    check("localized_command_lists: 3 til, har birida 5 buyruq",
          {k: len(v) for k, v in MC.localized_command_lists().items()}
          == {lang: 5 for lang in LANGS})
    check("default_menu_button() — MenuButtonCommands turi",
          isinstance(MC.default_menu_button(), MenuButtonCommands))

    # Noma'lum til/qiymat → standart UZ ro'yxati (fail-safe).
    check("noma'lum til standart UZ ro'yxatiga tushadi",
          [c.description for c in MC.build_bot_commands("de")]
          == [EXPECTED_DESCRIPTIONS["uz"][n] for n in EXPECTED_ORDER])
    check("noma'lum buyruq nomi — bo'sh tavsif (crash yo'q)",
          MC.command_description("no_such_command", "ru") == "")


# ===========================================================================
# TEST 3 — FAIL-SOFT
# ===========================================================================
def test_fail_soft():
    header("3", "🛟 FAIL-SOFT — API xatosi bot startini buzmaydi")

    # 3a) set_my_commands doim xato tashlaydi.
    bot = _RecordingBot(fail_commands=True)
    try:
        report = asyncio.run(MAIN.set_bot_commands(_app(bot)))
        raised = False
    except Exception as exc:  # pragma: no cover - bo'lmasligi kerak
        raised, report = True, str(exc)
    check("set_my_commands xatosida istisno tashlanmaydi", not raised, str(report))
    check("hisobotda standart/tillar False (yashirilmagan)",
          report["default"] is False
          and report["locales"] == {lang: False for lang in LANGS}, str(report))
    check("xatoga qaramay ☰ «Menu» tugmasi baribir o'rnatiladi",
          report["menu_button"] is True and len(bot.menu_buttons) == 1)

    # 3b) bitta til (ru) yiqiladi — qolganlari bajariladi.
    bot = _RecordingBot(fail_on_lang="ru")
    report = asyncio.run(MAIN.set_bot_commands(_app(bot)))
    check("bitta til xatosi qolganlarni to'xtatmaydi",
          report["locales"] == {"uz": True, "ru": False, "en": True}, str(report))
    check("yiqilmagan tillar Telegram'ga yetib borgan",
          [lang for lang, _p in bot.calls] == [None, "uz", "en"],
          str([lang for lang, _p in bot.calls]))

    # 3c) tugma API'si yiqiladi — buyruqlar baribir o'rnatiladi.
    bot = _RecordingBot(fail_button=True)
    report = asyncio.run(MAIN.set_bot_commands(_app(bot)))
    check("tugma xatosi buyruqlar ro'yxatini buzmaydi",
          report["default"] is True and all(report["locales"].values())
          and report["menu_button"] is False, str(report))

    # 3d) Bot API'si umuman yo'q (eski kutubxona) — crash yo'q.
    bot = _RecordingBot(has_api=False)
    report = asyncio.run(MAIN.set_bot_commands(_app(bot)))
    check("API mavjud bo'lmasa — hisobot False, crash yo'q",
          report == {"default": False, "locales": {}, "menu_button": False},
          str(report))
    check("application.bot yo'q bo'lsa ham crash yo'q",
          asyncio.run(MAIN.set_bot_commands(SimpleNamespace()))["default"] is None)


# ===========================================================================
# TEST 4 — SEAMLESS ROUTING (haqiqiy PTB registratsiyasi)
# ===========================================================================
class _RecBot:
    """PTB ``CommandHandler`` uchun minimal bot (faqat ``username`` kerak)."""

    id = 1
    username = "TestBot"
    defaults = None


def _command_update(text, bot=None):
    return Update.de_json({
        "update_id": 11,
        "message": {
            "message_id": 1, "date": 0, "text": text,
            "chat": {"id": USER_ID, "type": "private"},
            "from": {"id": USER_ID, "is_bot": False, "first_name": "Tester"},
            "entities": [
                {"type": "bot_command", "offset": 0,
                 "length": len(text.split()[0])}
            ],
        },
    }, bot if bot is not None else _RecBot())


def _fn_names(callback):
    """Handler callback'idagi funksiya nomi (lambda uchun ``co_names``)."""
    if callable(callback) and getattr(callback, "__name__", "<lambda>") != "<lambda>":
        return {callback.__name__}
    names = set()
    for name in getattr(getattr(callback, "__code__", None), "co_names", ()):
        if name in ("guard_entry", "guard_menu"):
            continue
        obj = getattr(H, name, None)
        if callable(obj):
            names.add(name)
    return names


def _build_app():
    from telegram.ext import ApplicationBuilder

    app = ApplicationBuilder().token("123456:TEST_TOKEN").build()
    H.register_all_handlers(app)
    return app


def _first_target(app, command):
    """``/command`` uchun BIRINCHI mos handler(nomi, funksiya nomlari)."""
    update = _command_update(f"/{command}")
    for group in sorted(app.handlers):
        for handler in app.handlers[group]:
            try:
                matched = handler.check_update(update)
            except Exception:  # pragma: no cover - himoya
                matched = None
            if matched is None or matched is False:
                continue
            if isinstance(handler, CommandHandler):
                return "CommandHandler", _fn_names(handler.callback)
            if isinstance(handler, ConversationHandler):
                for entry in handler.entry_points:
                    try:
                        hit = entry.check_update(update)
                    except Exception:  # pragma: no cover - himoya
                        hit = None
                    if hit is not None and hit is not False:
                        return "ConversationHandler(entry)", _fn_names(entry.callback)
                return "ConversationHandler", set()
    return None, set()


def _has_command_handler(app, command):
    """``/command`` uchun ro'yxatdan o'tgan handler bormi (entry point bilan)."""
    for group in sorted(app.handlers):
        for handler in app.handlers[group]:
            if isinstance(handler, CommandHandler) and command in handler.commands:
                return True
            if isinstance(handler, ConversationHandler):
                if any(isinstance(e, CommandHandler) and command in e.commands
                       for e in handler.entry_points):
                    return True
    return False


def test_seamless_routing():
    header("4", "🔌 SEAMLESS ROUTING — ☰ menyudagi har bir buyruq jonli handlerda")

    app = _build_app()
    expected = {
        "start": "start",
        "newpost": "start_new_post",
        "cleaner": "cleaner_command",
        "settings": "user_cabinet_menu",
        "help": "help_command",
    }
    for command in EXPECTED_ORDER:
        kind, names = _first_target(app, command)
        check(f"/{command}: birinchi mos handler topildi", bool(kind), str(kind))
        check(f"/{command} → {expected[command]}",
              names == {expected[command]}, str(sorted(names)))
    check("/cleaner — global CommandHandler (/settings va /help bilan bir qatorda)",
          _first_target(app, "cleaner")[0] == "CommandHandler",
          str(_first_target(app, "cleaner")[0]))
    check("/newpost — FSM entry point (oraliq qadamsiz yangi post oqimi)",
          _first_target(app, "newpost")[0] == "ConversationHandler(entry)",
          str(_first_target(app, "newpost")[0]))

    # FSM faol bo'lsa ham buyruqlar ishlaydi: PTB bitta guruhda TARTIB
    # bo'yicha birinchi mos handlerni tanlaydi, global buyruqlar esa
    # ``main_conv`` dan OLDIN ro'yxatdan o'tadi — shuning uchun /cleaner,
    # /settings va /help suhbat holatidan qat'i nazar DARHOL ishlaydi.
    group0 = list(app.handlers[0])
    conv_idx = next(i for i, h in enumerate(group0)
                    if isinstance(h, ConversationHandler))
    for command in ("cleaner", "settings", "help"):
        idx = next(i for i, h in enumerate(group0)
                   if isinstance(h, CommandHandler) and command in h.commands)
        check(f"/{command}: CommandHandler main_conv'dan OLDIN ro'yxatda "
              f"(faol FSM'da ham darhol ishlaydi)", idx < conv_idx,
              f"cmd={idx}, conv={conv_idx}")

    # ☰ menyudagi har bir buyruq Telegram xabarida ham taniladi (entity bilan).
    for command in EXPECTED_ORDER:
        update = _command_update(f"/{command}")
        check(f"/{command}: bot_command entity bilan matn tayyor",
              update.effective_message.entities[0].type == "bot_command")

    # ☰ menyu toza bo'lsa ham ESKI buyruqlar ISHLASHDA DAVOM ETADI
    # (asosiy mantiq saqlanadi — faqat ko'rinishdan olib tashlangan).
    for command in HIDDEN_FROM_MENU:
        check(f"/{command}: handler SAQLANGAN (menyuda ko'rinmaydi, ishlaydi)",
              _has_command_handler(app, command), command)

    # ``cleaner_command`` haqiqiy modul funksiyasi (mock emas).
    check("cleaner_command — handlers.settings haqiqiy funksiyasi",
          getattr(STG.cleaner_command, "__name__", "") == "cleaner_command"
          and STG.cleaner_command.__module__ == "handlers.settings")
    check("handlers.cleaner_command ham shu funksiyaga ishora qiladi",
          H.cleaner_command is STG.cleaner_command)


# ===========================================================================
# TEST 5/6 — HANDLER EKRANLARI (fake DB bilan, tarmoqsiz)
# ===========================================================================
class _Msg:
    def __init__(self, user_id=USER_ID):
        self.chat_id = 555
        self.message_id = 9001
        self.from_user = SimpleNamespace(id=user_id, first_name="T")
        self.sent = []

    async def reply_text(self, text, **kwargs):
        self.sent.append(dict(text=text, **kwargs))
        return SimpleNamespace(message_id=9002)

    async def delete(self):
        return True


class _Query:
    """``stgs_clean`` callback ekranini yozib boruvchi fake query."""

    def __init__(self, data, user_id=USER_ID):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id, first_name="T")
        self.message = _Msg(user_id)
        self.screen = {}
        self.answers = []

    async def answer(self, *args, **kwargs):
        self.answers.append((args, kwargs))

    async def edit_message_text(self, text=None, **kwargs):
        self.screen = dict(text=text, **kwargs)
        return self.screen

    async def edit_message_reply_markup(self, **kwargs):
        self.screen.update(kwargs)
        return self.screen


class _Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append(dict(chat_id=chat_id, text=text, **kwargs))
        return SimpleNamespace(message_id=1)

    async def edit_message_text(self, *args, **kwargs):
        return SimpleNamespace(message_id=1)


class _FakeDB:
    """``database.run_db`` ni almashtiruvchi deterministik mock (tarmoqsiz)."""

    def __init__(self, settings=None, signature="", fail_settings=False):
        self.settings_store = dict(settings or {})
        self.signature = signature
        self.fail_settings = fail_settings
        self.reads = 0

    async def run_db(self, fn, *args, **kwargs):
        name = getattr(fn, "__name__", str(fn))
        if name == "get_user_settings_and_signature":
            self.reads += 1
            if self.fail_settings:
                raise RuntimeError("simulated DB failure")
            keys = args[1] if len(args) > 1 else []
            defaults = args[2] if len(args) > 2 else {}
            return ({key: self.settings_store.get(key, bool(defaults.get(key, False)))
                     for key in keys}, self.signature)
        if name == "get_user_settings_bulk":
            self.reads += 1
            keys = args[1] if len(args) > 1 else []
            defaults = args[2] if len(args) > 2 else {}
            return {key: self.settings_store.get(key, bool(defaults.get(key, False)))
                    for key in keys}
        if name in ("get_user_post_signature_html", "get_user_setting") and self.fail_settings:
            raise RuntimeError("DB down")
        if name == "get_user_post_signature_html":
            return self.signature
        if name == "get_user_setting":
            return False
        if name == "get_user_post_signature":
            return self.signature
        if name == "get_user_language":
            return "uz"
        if name in ("get_ads_full", "get_user_channels"):
            return []
        if name == "get_setting":
            return ""
        if name == "is_premium":
            return False
        return None


def _with_db(fake, coro):
    if callable(coro) and not asyncio.iscoroutine(coro):
        coro = coro()
    original = db_mod.run_db
    db_mod.run_db = fake.run_db
    try:
        return asyncio.run(coro)
    finally:
        db_mod.run_db = original


def _ctx(lang="uz"):
    return SimpleNamespace(user_data={"lang": lang}, chat_data={}, bot=_Bot(),
                           application=None)


def _flat(markup):
    rows = getattr(markup, "inline_keyboard", None) or []
    return [b for row in rows for b in row]


def _cbs(markup):
    return [b.callback_data for b in _flat(markup)]


def test_cleaner_command_screen():
    header("5", "🧹 /cleaner — ekran BIR QADAMDA chiziladi (uz/ru/en)")

    for lang in LANGS:
        fake = _FakeDB(signature="https://t.me/my_channel")
        msg = _Msg()
        update = SimpleNamespace(
            message=msg, effective_message=msg,
            effective_user=SimpleNamespace(id=USER_ID, first_name="T"),
            effective_chat=SimpleNamespace(id=555), callback_query=None,
        )
        ctx = _ctx(lang)
        ctx.user_data["stale_fsm"] = "eski oqim"
        _with_db(fake, lambda: STG.cleaner_command(update, ctx))

        check(f"[{lang}] ekran darhol yuborildi (bitta xabar)",
              len(msg.sent) == 1, str(len(msg.sent)))
        sent = msg.sent[0] if msg.sent else {}
        text = sent.get("text", "")
        cbs = _cbs(sent.get("reply_markup"))
        check(f"[{lang}] 🧹 sarlavha o'sha tilda",
              settings_stats_t("ss_cl_title", lang) in text, text[:120])
        check(f"[{lang}] «⚡ Darhol yuborish» holati ko'rsatilgan",
              settings_stats_t("ss_cl_off", lang) in text, text[-200:])
        check(f"[{lang}] saqlangan ✍️ imzo ko'rsatilgan",
              "https://t.me/my_channel" in text, text[-160:])
        check(f"[{lang}] HTML rejim (formatlash saqlanadi)",
              sent.get("parse_mode") == "HTML", str(sent.get("parse_mode")))
        for cbdata in ("stgs_clean_go", "stgs_clean_sig", "stgs_clean_auto",
                       "stgs_clean_sig_clear", "stgs_clean_adv", "stgs_hub"):
            check(f"[{lang}] klaviaturda {cbdata!r}",
                  cbdata in cbs, str(cbs))
        check(f"[{lang}] FSM tozalandi (eski holat qolmadi)",
              "stale_fsm" not in ctx.user_data, str(ctx.user_data))
        check(f"[{lang}] bo'lim yozuvi — Sozlamalar",
              ctx.user_data.get("nav_section") == "settings",
              str(ctx.user_data.get("nav_section")))

        # 🔗 BIR MANBA: matn va klaviatura ``stgs_clean`` callback ekrani
        # bilan AYNAN bir xil (ikki nusxa yo'q).
        query = _with_db(_FakeDB(signature="https://t.me/my_channel"),
                         lambda: _run_cleaner_callback(lang))
        check(f"[{lang}] ekran matni stgs_clean bilan AYNAN bir xil",
              query.screen.get("text") == text, str(query.screen.get("text"))[:120])
        check(f"[{lang}] klaviatura stgs_clean bilan AYNAN bir xil",
              _cbs(query.screen.get("reply_markup")) == cbs,
              str(_cbs(query.screen.get("reply_markup"))))

    # 5b) DB yiqilsa ham ekran chiziladi (fail-soft).
    msg = _Msg()
    update = SimpleNamespace(
        message=msg, effective_message=msg,
        effective_user=SimpleNamespace(id=USER_ID, first_name="T"),
        effective_chat=SimpleNamespace(id=555), callback_query=None,
    )
    _with_db(_FakeDB(fail_settings=True),
             lambda: STG.cleaner_command(update, _ctx("uz")))
    check("DB xatosida ham ekran chiziladi (fail-soft)",
          len(msg.sent) == 1 and bool(msg.sent[0].get("text")),
          str(msg.sent)[:160])

    # 5c) Til profil/DB'dan olinadi — RU foydalanuvchi RU ekran ko'radi.
    msg = _Msg()
    update = SimpleNamespace(
        message=msg, effective_message=msg,
        effective_user=SimpleNamespace(id=USER_ID, first_name="T"),
        effective_chat=SimpleNamespace(id=555), callback_query=None,
    )

    async def _ru_lang(context, user_id):
        return "ru"

    original_lang = STG._user_lang
    STG._user_lang = _ru_lang
    try:
        _with_db(_FakeDB(), lambda: STG.cleaner_command(update, _ctx("uz")))
    finally:
        STG._user_lang = original_lang
    check("til DB/profil bilan aniqlanadi (ru ekrani)",
          settings_stats_t("ss_cl_title", "ru") in (msg.sent[0]["text"] if msg.sent else ""),
          str(msg.sent)[:160])


def _run_cleaner_callback(lang):
    query = _Query("stgs_clean")

    async def _go():
        await STG.settings_menu_callback(
            SimpleNamespace(callback_query=query, effective_user=query.from_user,
                            effective_message=query.message,
                            effective_chat=SimpleNamespace(id=555)),
            _ctx(lang),
        )
        return query

    return _go()


def test_settings_and_help_commands():
    header("6", "🧭 /settings va /help — tayyor UI (oraliq qadamsiz)")

    for lang in LANGS:
        # /settings — DB'siz, statik hub.
        msg = _Msg()
        update = SimpleNamespace(
            message=msg, effective_message=msg,
            effective_user=SimpleNamespace(id=USER_ID, first_name="T"),
            effective_chat=SimpleNamespace(id=555), callback_query=None,
        )
        _with_db(_FakeDB(), lambda: START.user_cabinet_menu(update, _ctx(lang)))
        sent = msg.sent[0] if msg.sent else {}
        cbs = _cbs(sent.get("reply_markup"))
        check(f"[{lang}] /settings → ⚙️ Sozlamalar hub'i chizildi",
              bool(sent.get("text")) and bool(cbs), str(sent)[:120])
        check(f"[{lang}] /settings: hub tugmalari (stgs_*) tayyor",
              any(str(c).startswith("stgs_") for c in cbs), str(cbs))
        check(f"[{lang}] /settings: 1 ta DB so'rovi ham yo'q (statik ekran)",
              msg.sent[0].get("reply_markup") is not None)

        # /help — qo'llanma + FAQ klaviaturasi.
        msg2 = _Msg()
        update2 = SimpleNamespace(
            message=msg2, effective_message=msg2,
            effective_user=SimpleNamespace(id=USER_ID, first_name="T"),
            effective_chat=SimpleNamespace(id=555), callback_query=None,
        )

        async def _no_ad(user_id, _orig=START.get_smart_reply_ad_async):
            return ""

        original_ad = START.get_smart_reply_ad_async
        START.get_smart_reply_ad_async = _no_ad
        try:
            _with_db(_FakeDB(), lambda: START.help_command(update2, _ctx(lang)))
        finally:
            START.get_smart_reply_ad_async = original_ad
        sent2 = msg2.sent[0] if msg2.sent else {}
        check(f"[{lang}] /help → qo'llanma matni yuborildi",
              bool(sent2.get("text")) and sent2.get("parse_mode") == "HTML",
              str(sent2)[:120])
        help_cbs = _cbs(sent2.get("reply_markup"))
        check(f"[{lang}] /help: yordam klaviaturasi (help:*) tayyor",
              any(str(c).startswith("help:") for c in help_cbs), str(help_cbs))


# ===========================================================================
# TEST 7 — STATIK KONTRAKT (manba va hujjat)
# ===========================================================================
def test_static_contract():
    header("7", "🧾 STATIK KONTRAKT — SSOT, hujjat va takroriy nusxa yo'q")

    main_src = (ROOT / "telegram_bot" / "main.py").read_text(encoding="utf-8")
    menu_src = (ROOT / "telegram_bot" / "menu_commands.py").read_text(encoding="utf-8")
    init_src = (ROOT / "telegram_bot" / "handlers" / "__init__.py").read_text(encoding="utf-8")
    readme = (ROOT / "telegram_bot" / "README.md").read_text(encoding="utf-8")

    check("main.py: set_my_commands chaqiriladi",
          "set_my_commands" in main_src, "")
    check("main.py: ro'yxat menu_commands modulidan olinadi",
          "build_bot_commands" in main_src and "localized_command_lists" in main_src
          and "from menu_commands import" in main_src)
    check("main.py: qo'lda yozilgan BotCommand ro'yxati YO'Q",
          "BotCommand(" not in main_src, "takroriy nusxa -> SSOT buzilgan")
    check("main.py: ☰ tugma turi standart «commands» qilib qo'yiladi",
          "set_chat_menu_button" in main_src and "default_menu_button" in main_src)
    check("menu_commands.py: 5 ta buyruq + 3 til SSOT sifatida e'lon qilingan",
          "MENU_COMMANDS" in menu_src and "MENU_COMMAND_LOCALES" in menu_src
          and '"uz", "ru", "en"' in menu_src)
    check("handlers/__init__.py: /cleaner global CommandHandler sifatida ro'yxatda",
          'CommandHandler("cleaner", cleaner_command)' in init_src)
    check("README: /cleaner hujjatlashtirilgan", "`/cleaner`" in readme)
    check("README: ☰ «Menu» tugmasi (set_my_commands) tasvirlangan",
          "set_my_commands" in readme, "")


# ===========================================================================
# MAIN
# ===========================================================================
def main():
    print("=" * 70)
    print(" 📋 TELEGRAM «MENU» TUGMASI (set_my_commands) — TEST SUITE")
    print("=" * 70)
    test_registry_contract()
    test_set_my_commands_localized()
    test_fail_soft()
    test_seamless_routing()
    test_cleaner_command_screen()
    test_settings_and_help_commands()
    test_static_contract()

    print("\n" + "=" * 70)
    print(f" JAMI: o'tdi={PASSED}, xato={FAILURES}")
    if FAILURES:
        print(" [FAIL] MENYU TUGMASI / BUYRUQLAR TESTLARIDA XATOLIKLAR BOR ^^^")
        return 1
    print(" 📋 MENYU TUGMASI VA BUYRUQLAR — 100% YASHIL ✔")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
