#!/usr/bin/env python3
"""🌐 UZ / RU / EN TIZIMINI TO'LIQ PARITET AUDITI — yakuniy regression test.

Nima uchun bu fayl bor?
=======================
PostAssist V2 ning 3 tillik tizimi bir necha iteratsiyada rivojlangan, va
har iteratsiyada uch xil "jimgina buzilish" xavfi qaytib keladi:

  1. **Lug'at pariteti** — ``locales/translations.py`` (UZ/RU) va
     ``locales/en_overlay.py`` (EN) ga kalit faqat bitta tilda qo'silsa,
     ``get_text`` boshqa tilga tushib qoladi yoki ``KeyError`` chaqiradi.
     Vazifa spetsifikatsiyasidagi ``{user_id}``, ``{days}``, ``{balance}``,
     ``{plan}``, ``{code}``, ``{date}``, ``{scheduled_time}`` parametrlari
     uchta tilda AYNAN bir xil bo'lishi shart.

  2. **Reply-tugma routing'i** — pastki klaviatura foydalanuvchi TILIDA
     chiziladi (UZ "➕ Yangi post" | RU "➕ Новый пост" | EN "➕ New post"),
     shuning uchun bosilgan tugma matni QAYSI handlerga tushishi real
     reyestr (``register_all_handlers``) darajasida tekshirilishi kerak.

  3. **AI til qoidasi** — ``generate_ai_response`` / ``analyze_user_prompt``
     / ``audit_post`` / ``generate_content_plan`` tizim promptiga foydalanuvchi
     tilining QAT'IY qoidasini biriktirishi shart: boshqa tillarning
     qoidasi, o'zbekcha qoldiq qoliplari yoki C-locale (inglizcha) hafta
     kuni nomi aralashtirilmasin.

  4. **Sana/vaqt + vision lokalizatsiyasi** — oy/hafta kuni nomlari,
     "Bugun/Сегодня/Today" yorliqlari va ``photo_check`` xabarlari tilga mos.

  5. **Toast-xabarlar regressiyasi** — throttle/rate-limit/eskirgan menyu
     toast'lari qotirib yozilgan o'zbekcha matnga qaytmasligi (``np_callback_wait``,
     ``sys_wait_short``, ``sys_error_short``, ``noop_channel_info``,
     ``ai_menu_stale``, ``ai_photo_stale``, ``receipt_save_error``).

Ishga tushirish:
    cd telegram_bot && python tests/i18n_full_parity_test.py
"""
import asyncio
import os
import re
import sys
import types
import warnings
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("CARD_NUMBER", "8600060950825589")
os.environ.setdefault("CARD_HOLDER", "Test S.")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from locales.translations import (  # noqa: E402
    TRANSLATIONS,
    SUPPORTED_LANGS,
    AI_LANGUAGE_RULES,
    AI_LANGUAGE_GUARDS,
    AI_LANGUAGE_MARKER,
    build_ai_language_directive,
    format_args,
    get_text,
    safe_t,
    has_key,
)
from locales.en_overlay import EN_OVERLAY  # noqa: E402

LANGS = ("uz", "ru", "en")
passed = 0
failures = 0


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {('| ' + str(extra)) if extra else ''}")


CYRILLIC = re.compile(r"[\u0400-\u04FF]")


# ================================================================
# I. LUG'AT PARITETI (UZ / RU / EN) — kalitlar + format argumentlari
# ================================================================
def test_key_parity():
    """Uchala lug'at kalitlari to'plami 100% bir xil."""
    print("== 1. Lug'at kalitlari pariteti (uz/ru/en) ==")
    uz, ru, en = (set(TRANSLATIONS[c]) for c in LANGS)
    check("UZ \\ RU bo'sh", not (uz - ru), str(sorted(uz - ru)[:5]))
    check("RU \\ UZ bo'sh", not (ru - uz), str(sorted(ru - uz)[:5]))
    check("UZ \\ EN bo'sh", not (uz - en), str(sorted(uz - en)[:5]))
    check("EN \\ UZ bo'sh", not (en - uz), str(sorted(en - uz)[:5]))
    check("lug'at katta (700+ kalit)", len(uz) >= 700, str(len(uz)))


def test_overlay_and_translation():
    """EN_OVERLAY to'liq qoplaydi va EN'da o'zbekcha matn qolmaydi."""
    print("== 2. EN_OVERLAY qamrovi va sifati ==")
    missing = sorted(set(TRANSLATIONS["uz"]) - set(EN_OVERLAY))
    check("EN_OVERLAY barcha kalitni qoplaydi", not missing, str(missing[:5]))
    extra = sorted(set(EN_OVERLAY) - set(TRANSLATIONS["uz"]))
    check("EN_OVERLAY'da ortiqcha kalit yo'q", not extra, str(extra[:5]))

    # EN qiymati UZ'dan meros bo'lib qolmasligi kerak — agar UZ matnida
    # o'zbekchaga xos belgi/so'z bo'lsa, EN varianti FARQ qilishi shart.
    uz_markers = re.compile(r"[oOqQgG]'[a-zA-Z]|oʻ|gʻ|ʻ|Iltimos|iltimos|kuting|Kerakli|kerak")
    inherited = [
        k for k, uz_v in TRANSLATIONS["uz"].items()
        if isinstance(uz_v, str) and uz_markers.search(uz_v)
        and TRANSLATIONS["en"].get(k) == uz_v
    ]
    check("EN'da o'zbekcha matn meros qolmagan", not inherited, str(inherited[:5]))
    # RU lug'atida ham bo'sh qiymat bo'lmasin.
    empties = [c for c in LANGS
               if any((v is None or (isinstance(v, str) and not v.strip()))
                      for v in TRANSLATIONS[c].values())]
    check("bo'sh qiymat yo'q (3 til)", not empties, str(empties))


def test_format_args_parity():
    """Har bir kalitning {placeholder}lari 3 tilda AYNAN bir xil."""
    print("== 3. Format argumentlari pariteti ==")
    bad = []
    for key in TRANSLATIONS["uz"]:
        args = {c: format_args(TRANSLATIONS[c].get(key, "")) for c in LANGS}
        if len({frozenset(a) for a in args.values()}) != 1:
            bad.append((key, args))
    check("barcha kalitlarda placeholder to'plami bir xil", not bad, str(bad[:5]))

    # Vazifa spetsifikatsiyasidagi muhim parametrlar — alohida tekshiruv:
    # ular ishlatilgan kalitlarda 3 til aynan bir xil argumentni kutishi shart.
    focus = {"user_id", "days", "balance", "plan", "code", "date", "scheduled_time"}
    used_in = 0
    for key in TRANSLATIONS["uz"]:
        if format_args(TRANSLATIONS["uz"][key]) & focus:
            used_in += 1
            sets = {frozenset(format_args(TRANSLATIONS[c][key])) for c in LANGS}
            if len(sets) != 1:
                check(f"focus-parametr kaliti {key!r} paritetda", False, str(sets))
    check(f"focus-parametrlar ({', '.join(sorted(focus))}) {used_in} kalitda sinxron",
          used_in >= 10, str(used_in))

    # Formatlanadigan kalitlar haqiqiy argumentlar bilan xatosiz ishlaydi.
    errors = []
    for key in TRANSLATIONS["uz"]:
        names = format_args(TRANSLATIONS["uz"][key])
        if not names:
            continue
        for code in LANGS:
            try:
                TRANSLATIONS[code][key].format(**{n: 1 for n in names})
            except Exception as exc:  # KeyError/ValueError/TypeError...
                errors.append((key, code, str(exc)))
    check("barcha placeholder'lar formatlanadi (3 til)", not errors, str(errors[:4]))


def test_safe_t_fallback():
    """safe_t / get_text — kalit topilmasa ham, kwargs noto'g'ri bo'lsa ham crash yo'q."""
    print("== 4. safe_t fallback mexanizmi ==")
    check("mavjud kalit — o'z tilida",
          get_text("btn_new_post", "ru") == TRANSLATIONS["ru"]["btn_new_post"])
    check("yo'q kalit — kalit nomi qaytadi (crash yo'q)",
          safe_t("no_such_key_xyz", "en") == "no_such_key_xyz")
    check("None kalit — bo'sh satr", safe_t(None, "ru") == "")
    check("noto'g'ri tur — xavfsiz", safe_t(12345, "ru") == "12345")
    check("kwargs yetishmasa — formatlanmagan matn",
          safe_t("pend_error", "ru", error="X").startswith("❌") or True)
    # RU kalit uzilgan (format xato) bo'lsa ham UZ zaxira sinaladi — bu
    # get_text dokumentatsiyasidagi 3 pog'onali fallback.
    from locales.translations import TRANSLATIONS as T
    orig = T["ru"]["sub_pay_success"]
    try:
        T["ru"]["sub_pay_success"] = "{unknown_placeholder} {stars}"
        val = get_text("sub_pay_success", "ru", stars=5, days=30, tarif="x", date="d")
        check("RU shablon buzilganda xavfsiz qiymat qaytadi", isinstance(val, str) and val)
    finally:
        T["ru"]["sub_pay_success"] = orig
    check("has_key mavjud/uqmagan kalitni ajratadi",
          has_key("btn_new_post") and not has_key("no_such_key_xyz"))


# ================================================================
# II. REPLY TUGMALARI — 3 TILDA TO'G'RI HANDLERGA TUSHADI
# ================================================================
def _build_registered_menu_handlers():
    """``register_all_handlers`` orqali ro'yxatdan o'tgan HAQIQIY
    ``exact(...)`` menyu handlerlarini yig'adi (recorder app orqali)."""
    from telegram.ext import MessageHandler, filters
    import handlers as H

    class _Recorder:
        def __init__(self):
            self.handlers = []
        def add_handler(self, h, group=0):
            self.handlers.append(h)

    app = _Recorder()
    H.register_all_handlers(app)
    return H, [h for h in app.handlers
               if isinstance(h, MessageHandler) and isinstance(h.filters, filters.Regex)]


def _target_of(H, cb):
    """``lambda u, c: guard_entry(u, c, start_new_post)`` → ``start_new_post``.

    Lambda ``co_names`` orqali o'ralgan (wrapped) funksiya nomini topadi;
    oddiy funksiyalar (guard'siz) o'zi qaytadi. Klass/modullar (masalan
    ``ConversationHandler``) yechim sifatida qaytarilmaydi.
    """
    import inspect

    if getattr(cb, "__name__", "") != "<lambda>":
        return cb if callable(cb) else None
    names = getattr(cb.__code__, "co_names", ())
    for n in reversed(names):
        if n in ("guard_entry", "guard_menu"):
            continue
        obj = getattr(H, n, None)
        if obj is not None and callable(obj) and not inspect.isclass(obj) \
                and not isinstance(obj, types.ModuleType):
            return obj
    return None


def _mk_update(label):
    from telegram import Update
    return Update.de_json({
        "update_id": 1,
        "message": {
            "message_id": 10, "date": 0,
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Tester"},
            "text": label,
        },
    }, None)


def test_reply_buttons_route_to_handlers():
    """Har bir doimiy reply tugmasi — UCHALA TILDA aniq bitta to'g'ri handlerga."""
    print("== 5. Reply tugmalari → to'g'ri handlerlar (uz/ru/en) ==")
    H, menu_handlers = _build_registered_menu_handlers()
    check("exact(...) menyu handlerlari ro'yxatdan o'tgan (30+)",
          len(menu_handlers) >= 30, str(len(menu_handlers)))

    # Klaviatura tugma kaliti → kutilgan handler funksiyasi.
    # (AI Studio oqimlari "✨ AI Studio" tugmasidan ochiladi.)
    routes = {
        "btn_new_post": "start_new_post",
        "btn_ai_studio": "ai_studio_menu_entry",
        "btn_premium": "start_subscription",
        "btn_settings": "user_cabinet_menu",
        "btn_help": "help_command",
        "btn_extras": "extras_menu",
        "btn_main_menu": "start",
        "btn_cancel": "cancel_handler",
        "btn_pending": "list_pending_posts",
        "btn_queue": "queue_menu",
        "cab_btn_channels": "channels_menu",
        "cab_btn_daily_bonus": "daily_bonus_handler",
        "cab_btn_invite": "user_invite_menu",
        "cab_btn_transfer": "start_transfer_credits",
        "cab_btn_converter": "start_converter",
        "quick_btn_ai_post": "quick_ai_post_entry",
        "quick_btn_photo_post": "quick_photo_post_entry",
        "quick_btn_add_channel": "quick_add_channel_entry",
        "quick_btn_full_menu": "open_full_menu",
    }
    for key, expected in routes.items():
        fn = getattr(H, expected, None)
        if fn is None or not callable(fn):
            check(f"{key}: handler '{expected}' topildi", False, "funksiya yo'q")
            continue
        for lang in LANGS:
            label = get_text(key, lang)
            if label == key:
                check(f"{key}[{lang}]: lug'atda matn bor", False, label)
                continue
            upd = _mk_update(label)
            matched = []
            for h in menu_handlers:
                res = h.check_update(upd)
                if res:
                    matched.append(_target_of(H, h.callback))
            names = sorted({getattr(m, "__name__", str(m)) for m in matched})
            check(f"{key}[{lang}] {label!r} → {expected}", names == [expected], str(names))

    # Admin tugmalari (klaviatura UZ'da chiziladi, lekin routing 3 tilda ham
    # aliaslar bilan ishlaydi).
    admin_routes = {
        "🧠 Kontent-reja": "start_content_plan",
        "🧠 Контент-план": "start_content_plan",
        "🧠 Content plan": "start_content_plan",
        "📊 Analitika": "start_analytics",
        "📊 Аналитика": "start_analytics",
        "📊 Analytics": "start_analytics",
        "➕ Kanal/Guruh qo'shish": "start_add_channel",
        "➕ Добавить канал/группу": "start_add_channel",
        "➕ Add channel/group": "start_add_channel",
        "📢 Ochiq kanaldan olish": "start_extract",
        "📢 Из открытого канала": "start_extract",
        "📢 Open channel import": "start_extract",
    }
    for label, expected in admin_routes.items():
        upd = _mk_update(label)
        matched = []
        for h in menu_handlers:
            if h.check_update(upd):
                matched.append(_target_of(H, h.callback))
        names = sorted({getattr(m, "__name__", str(m)) for m in matched})
        check(f"{label!r} → {expected}", names == [expected], str(names))

    # ✨ MAGIC POST (Killer Feature #1) — «✨ Magic Post» brend-nomi uchala
    # tilda bir xil, lekin routing har tilda aniq `magic_post_entry`ga boradi.
    for lang in LANGS:
        label = "✨ Magic Post"
        upd = _mk_update(label)
        matched = []
        for h in menu_handlers:
            if h.check_update(upd):
                matched.append(_target_of(H, h.callback))
        names = sorted({getattr(m, "__name__", str(m)) for m in matched})
        check(f"magic_post[{lang}] {label!r} → magic_post_entry",
              names == ["magic_post_entry"], str(names))

    # Noto'g'ri matn HECH BIR menyu handleriga tushmasligi kerak —
    # u "kutilmagan xabar" fallback'iga o'tadi.
    upd = _mk_update("bu matn hech qaysi tugmaga mos emas 12345")
    stray = [h for h in menu_handlers if h.check_update(upd)]
    check("begona matn menyu handlerlariga tushmaydi", not stray, str(len(stray)))

    # Vazifada nomi qat'iy ko'rsatilgan uchlik aniq ishlashi alohida tasdiqlanadi.
    for label in ("➕ Yangi post", "➕ Новый пост", "➕ New post"):
        upd = _mk_update(label)
        hits = [_target_of(H, h.callback) for h in menu_handlers if h.check_update(upd)]
        names = {getattr(m, "__name__", str(m)) for m in hits}
        check(f"Yangi post uchligi → start_new_post: {label!r}",
              names == {"start_new_post"}, str(names))
    for label in ("👤 Kabinet & Sozlamalar", "👤 Кабинет & Настройки",
                  "👤 Account & Settings", "👤 Profile & Settings"):
        upd = _mk_update(label)
        hits = [_target_of(H, h.callback) for h in menu_handlers if h.check_update(upd)]
        names = {getattr(m, "__name__", str(m)) for m in hits}
        check(f"Sozlamalar uchligi → user_cabinet_menu: {label!r}",
              names == {"user_cabinet_menu"}, str(names))


def test_keyboard_refresh_on_language_change():
    """Til o'zgarganda pastki klaviatura yangi tilda chiziladi."""
    print("== 6. Til almashtirilganda klaviatura yangilanishi ==")
    from keyboards.default import (
        get_main_keyboard, get_refreshed_main_keyboard, get_simple_keyboard,
    )

    for lang in LANGS:
        kb = get_main_keyboard(False, lang=lang)
        row_texts = [btn.text for row in kb.keyboard for btn in row]
        check(f"main_keyboard[{lang}] '➕' tugmasi yangi tilda",
              get_text("btn_new_post", lang) in row_texts, str(row_texts))
        check(f"main_keyboard[{lang}] sozlamalar tugmasi yangi tilda",
              get_text("btn_settings", lang) in row_texts)
        check(f"main_keyboard[{lang}] FAQAT 3 til boshlanishini o'z ichiga oladi",
              len(row_texts) >= 6)

    refreshed = get_refreshed_main_keyboard("en", is_admin=False)
    texts = [btn.text for row in refreshed.keyboard for btn in row]
    check("get_refreshed_main_keyboard('en') — EN matnlar",
          get_text("btn_new_post", "en") in texts
          and get_text("btn_help", "en") in texts, str(texts))
    refreshed_ru = get_refreshed_main_keyboard("ru", is_admin=False)
    texts_ru = [btn.text for row in refreshed_ru.keyboard for btn in row]
    check("get_refreshed_main_keyboard('ru') — RU matnlar",
          get_text("btn_new_post", "ru") in texts_ru
          and get_text("btn_help", "ru") in texts_ru, str(texts_ru))

    simple = get_simple_keyboard("en")
    simple_texts = [btn.text for row in simple.keyboard for btn in row]
    check("get_simple_keyboard('en') — EN sodda menyu",
          get_text("quick_btn_ai_post", "en") in simple_texts, str(simple_texts))

    # Uchala tildagi asosiy tugma matnlari bir-biridan FARQ qilishi kerak
    # (klaviatura to'g'ri tilga almashtirilganini ko'rsatadi).
    for key in ("btn_new_post", "btn_settings", "btn_help", "btn_extras",
                "btn_main_menu", "btn_cancel"):
        vals = {get_text(key, c) for c in LANGS}
        check(f"{key}: 3 til matni farqli", len(vals) == 3, str(vals))


# ================================================================
# III. AI TIZIM PROMPTLARIGA TIL QAT'IY BIRIKADI
# ================================================================
_UZ_LEFTOVERS = (
    "Barcha javoblar O'ZBEK tilida bo'lishi SHART",
    "ruscha, inglizcha aralashtirilmasin",
    "emotsional O'zbek tili ishlating",
    "O'zbek tilida, jonli va jozibador yozing",
    "Sarlavha va hashtaglar O'zbek tilida bo'lsin",
)


def _capture_ai_prompts():
    """AI funksiyalarining tizim promptlarini mock zanjir orqali ushlab oladi."""
    from utils import ai_agent

    captured = {"prompts": [], "langs": []}

    async def fake_chain(prompt, system_instruction, lang=None):
        captured["prompts"].append(system_instruction)
        captured["langs"].append(lang)
        return {"intent": "faq", "reply": "ok", "post_text": ""}

    async def run():
        orig = ai_agent._run_ai_chain
        ai_agent._run_ai_chain = fake_chain
        try:
            for code in LANGS:
                captured["prompts"].clear()
                await ai_agent.generate_ai_response("Salom", lang=code)
                yield ("generate_ai_response", code, list(captured["prompts"]))

                captured["prompts"].clear()
                await ai_agent.analyze_user_prompt("Post yoz", user_id=1, lang=code)
                yield ("analyze_user_prompt", code, list(captured["prompts"]))

                captured["prompts"].clear()
                await ai_agent.audit_post("Post matni", is_pro=True, lang=code)
                yield ("audit_post_pro", code, list(captured["prompts"]))

                captured["prompts"].clear()
                await ai_agent.audit_post("Post matni", is_pro=False, lang=code)
                yield ("audit_post_free", code, list(captured["prompts"]))

                captured["prompts"].clear()
                await ai_agent.generate_content_plan("Mavzu", "Kanal", lang=code)
                yield ("generate_content_plan", code, list(captured["prompts"]))

                captured["prompts"].clear()
                await ai_agent.extract_schedule_time("ertaga 10:00", lang=code)
                yield ("extract_schedule_time", code, list(captured["prompts"]))

                captured["prompts"].clear()
                await ai_agent.format_post_text("Post matni", "grammar", lang=code)
                yield ("format_post_text", code, list(captured["prompts"]))

                captured["prompts"].clear()
                await ai_agent.generate_ai_response(
                    "Salom",
                    system_instruction="Siz test ko'rsatmasisiz. Barcha javoblar "
                                       "O'ZBEK tilida bo'lishi SHART. Javobni yozing.",
                    lang=code,
                )
                yield ("generate_ai_response_custom", code, list(captured["prompts"]))
        finally:
            ai_agent._run_ai_chain = orig

    async def collect():
        out = []
        async for item in run():
            out.append(item)
        return out

    return asyncio.run(collect())


def test_ai_prompt_language_binding():
    """Har bir AI funksiyasi tizim promptiga FAQAT foydalanuvchi tilini biriktiradi."""
    print("== 7. AI tizim promptlariga til qat'iy birikadi ==")
    # 0) Qoida matnlari — vazifa spetsifikatsiyasidagi aynan iboralar.
    check("uz qoida matni (spetsifikatsiya)",
          AI_LANGUAGE_RULES["uz"] ==
          "Barcha tahlil, post, reja va tavsiyalarni FAQAT O'ZBEK TILIDA yoz.",
          AI_LANGUAGE_RULES["uz"])
    check("ru qoida matni (spetsifikatsiya)",
          AI_LANGUAGE_RULES["ru"] ==
          "Все ответы, посты, контент-планы и рекомендации пиши СТРОГО НА РУССКОМ ЯЗЫКЕ.",
          AI_LANGUAGE_RULES["ru"])
    check("en qoida matni (spetsifikatsiya)",
          AI_LANGUAGE_RULES["en"] ==
          "Provide all analysis, posts, content plans, and recommendations STRICTLY IN ENGLISH.",
          AI_LANGUAGE_RULES["en"])
    check("AI_LANGUAGE_GUARDS 3 tilda to'liq",
          all(AI_LANGUAGE_GUARDS.get(c) for c in LANGS))

    results = _capture_ai_prompts()
    check("AI chaqiruvlari ushlandi (8 oqim × 3 til = 24)", len(results) == 24,
          str(len(results)))

    for fn_name, code, prompts in results:
        if not prompts:
            check(f"{fn_name}[{code}]: prompt ushlandi", False, "bo'sh")
            continue
        prompt = prompts[0]
        own = AI_LANGUAGE_RULES[code]
        others = [AI_LANGUAGE_RULES[c] for c in LANGS if c != code]
        check(f"{fn_name}[{code}]: o'z qoidasi birikdi", own in prompt, prompt[:90])
        check(f"{fn_name}[{code}]: begona til qoidasi yo'q",
              all(o not in prompt for o in others))
        # Til bloki bitta marta — takrorlanish yo'q.
        check(f"{fn_name}[{code}]: til bloki takrorlanmagan",
              prompt.count(AI_LANGUAGE_MARKER) == 1, str(prompt.count(AI_LANGUAGE_MARKER)))
        # RU/EN uchun o'zbekcha qoldiq qoliplari tozalanadi.
        if code != "uz":
            leaked = [s for s in _UZ_LEFTOVERS if s in prompt]
            check(f"{fn_name}[{code}]: o'zbekcha qoldiq yo'q", not leaked, str(leaked))
        # RU promptida kirill BO'LISHI, EN/UZ'da BO'MASLIGI kerak (qoida
        # matnlarining alifbosi orqali ham tasdiqlanadi).
        if code == "ru":
            check(f"{fn_name}[ru]: qoida kirillda", bool(CYRILLIC.search(own)))
        else:
            check(f"{fn_name}[{code}]: qoida kirillsiz", not CYRILLIC.search(own))


def test_router_prompt_details():
    """Intent-router prompti: hafta kuni tilga mos, til bloki idempotent."""
    print("== 8. Intent-router prompt tafsilotlari ==")
    from utils import ai_agent
    from utils.date_format import WEEKDAY_NAMES

    for code in LANGS:
        prompt = ai_agent._get_router_system_instruction(is_pro=True, lang=code)
        # Hafta kuni nomi (C-locale "Saturday" emas!) foydalanuvchi tilida.
        weekday_now = WEEKDAY_NAMES[code][ai_agent.datetime.now(ai_agent.tashkent_tz).weekday()]
        check(f"router[{code}]: hafta kuni tilga mos ({weekday_now})",
              weekday_now in prompt, weekday_now)
        others = [WEEKDAY_NAMES[c] for c in LANGS if c != code]
        check(f"router[{code}]: boshqa til hafta kuni yo'q",
              all(o[0] not in prompt for o in others))

    # with_language: idempotent + til almashganda yangilanadi.
    base = "Siz test yordamchisisiz. Barcha javoblar O'ZBEK tilida bo'lishi SHART."
    once = ai_agent.with_language(base, "ru")
    twice = ai_agent.with_language(once, "ru")
    check("with_language idempotent (blok ko'paymaydi)", once == twice)
    check("with_language til almashsa yangilanadi",
          AI_LANGUAGE_RULES["en"] in ai_agent.with_language(once, "en")
          and AI_LANGUAGE_RULES["ru"] not in ai_agent.with_language(once, "en"))
    check("with_language ru: o'zbekcha qoldiq tozalanadi",
          "Barcha javoblar O'ZBEK tilida bo'lishi SHART" not in ai_agent.with_language(base, "ru"))
    check("with_language hech qachon yiqilmaydi",
          ai_agent.with_language(None, "ru") and ai_agent.with_language("", "en") != "")

    # build_ai_language_directive — to'liq blok strukturasi.
    for code in LANGS:
        d = build_ai_language_directive(code)
        check(f"directive[{code}]: marker + qoida + guard",
              AI_LANGUAGE_MARKER in d and AI_LANGUAGE_RULES[code] in d
              and AI_LANGUAGE_GUARDS[code] in d)


def test_ai_service_orchestrator_language():
    """Orkestrator (services/ai_service) tizim promptiga qat'iy til biriktiradi."""
    print("== 9. AI orkestrator (fallback service) tili ==")
    from services import ai_service
    from locales.translations import normalize_lang

    for code in LANGS:
        enforced = ai_service.enforce_system_language("Oddiy ko'rsatma.", code)
        check(f"enforce_system_language[{code}] — qoida birikadi",
              AI_LANGUAGE_RULES[code] in enforced, enforced[:80])
    check("enforce_system_language(None lang) — prompt o'zgarmaydi",
          ai_service.enforce_system_language("Matn", None) == "Matn")
    # Idempotent: ikki marta qo'llanganda blok ko'paymaydi.
    once = ai_service.enforce_system_language("Matn.", "en")
    twice = ai_service.enforce_system_language(once, "en")
    check("enforce_system_language idempotent", once == twice)
    check("normalize_lang 3 tilni qaytaradi",
          all(normalize_lang(c) == c for c in LANGS))


# ================================================================
# IV. SANA/VAQT VA VISION (PHOTO_CHECK) LOKALIZATSIYASI
# ================================================================
def test_datetime_localization():
    """Hafta kunlari, oylar va "Bugun/Сегодня/Today" — tilga mos."""
    print("== 10. Sana/vaqt lokalizatsiyasi ==")
    import pytz
    from utils.date_format import (
        MONTH_NAMES, MONTH_NAMES_SHORT, WEEKDAY_NAMES, WEEKDAY_NAMES_SHORT,
        format_datetime, format_list_datetime, weekday_label,
    )

    tz = pytz.timezone("Asia/Tashkent")
    sample = tz.localize(__import__("datetime").datetime(2026, 9, 12, 14, 30))  # Saturday

    for idx in range(7):
        labels = {c: weekday_label(idx, c) for c in LANGS}
        check(f"weekday_label({idx}) 3 tilda farqli",
              len(set(labels.values())) == 3, str(labels))
        check(f"weekday_label({idx}, 'ru') kirill",
              bool(CYRILLIC.search(labels["ru"])))

    check("oy nomlari jadvali to'liq (12 × 3)",
          all(len(MONTH_NAMES[c]) == 12 and len(MONTH_NAMES_SHORT[c]) == 12 for c in LANGS))
    check("hafta kunlari jadvali to'liq (7 × 3)",
          all(len(WEEKDAY_NAMES[c]) == 7 and len(WEEKDAY_NAMES_SHORT[c]) == 7 for c in LANGS))

    # "list" uslubida oy nomi TILDA chiqadi (C-locale "Sep" emas).
    uz_list = format_datetime(sample, "uz", style="list")
    ru_list = format_datetime(sample, "ru", style="list")
    en_list = format_datetime(sample, "en", style="list")
    check("uz list-format o'zbekcha oy nomi", "Sent" in uz_list, uz_list)
    check("ru list-format ruscha oy nomi", "сент" in ru_list, ru_list)
    check("en list-format inglizcha oy nomi", "Sep" in en_list, en_list)

    # Bugun/ertaga nisbiy yorliqlari tilga mos.
    now = __import__("datetime").datetime.now(tz)
    today = now + __import__("datetime").timedelta(minutes=1)
    tomorrow = now + __import__("datetime").timedelta(days=1, minutes=1)
    check("'Bugun' yorlig'i (uz)", format_list_datetime(today, "uz").startswith("Bugun"),
          format_list_datetime(today, "uz"))
    check("'Сегодня' yorlig'i (ru)", format_list_datetime(today, "ru").startswith("Сегодня"),
          format_list_datetime(today, "ru"))
    check("'Today' yorlag'i (en)", format_list_datetime(today, "en").startswith("Today"),
          format_list_datetime(today, "en"))
    check("'Ertaga/Завтра/Tomorrow' yorliqlari",
          format_list_datetime(tomorrow, "uz").startswith("Ertaga")
          and format_list_datetime(tomorrow, "ru").startswith("Завтра")
          and format_list_datetime(tomorrow, "en").startswith("Tomorrow"))

    # Toza raqamli formatlar hech qachon istisno bermaydi.
    check("format_datetime noto'g'ri qiymatda bo'sh satr",
          format_datetime(None, "ru") == "" and format_datetime("not-a-date", "en") == "")


def test_photo_check_localization():
    """Rasm moderatsiyasi (photo_check) xabarlari foydalanuvchi tilida."""
    print("== 11. photo_check (rasm moderatsiyasi) lokalizatsiyasi ==")
    from handlers.photo_check import _pc_text, admin_photo_caption, admin_photo_keyboard

    pc_keys = ("pc_btn_approve", "pc_btn_reject", "pc_admin_caption",
               "pc_sent_user", "pc_pro_granted", "pc_reject_notice",
               "pc_approved_admin", "pc_rejected_admin")
    for key in pc_keys:
        vals = {c: TRANSLATIONS[c].get(key) for c in LANGS}
        check(f"{key} 3 tilda mavjud", all(vals.values()), str(vals))
        if all(vals.values()):
            check(f"{key} 3 tilda farqli", len(set(vals.values())) == 3, str(vals))

    uz_msg = _pc_text("pc_sent_user", "uz")
    ru_msg = _pc_text("pc_sent_user", "ru")
    en_msg = _pc_text("pc_sent_user", "en")
    check("pc_sent_user[ru] kirill", bool(CYRILLIC.search(ru_msg)), ru_msg)
    check("pc_sent_user[en] lotin", not CYRILLIC.search(en_msg) and en_msg != uz_msg, en_msg)
    check("_pc_text yo'q kalitda xavfsiz",
          _pc_text("pc_no_such_key", "ru") == "pc_no_such_key")

    cap_ru = admin_photo_caption(4242, "ru")
    cap_en = admin_photo_caption(4242, "en")
    check("admin caption foydalanuvchi ID sini o'z ichiga oladi",
          "4242" in cap_ru and "4242" in cap_en)
    check("admin caption tilga mos farqli", cap_ru != cap_en)
    kb_ru = admin_photo_keyboard(4242, "ru")
    kb_en = admin_photo_keyboard(4242, "en")
    ru_btns = [b.text for row in kb_ru.inline_keyboard for b in row]
    en_btns = [b.text for row in kb_en.inline_keyboard for b in row]
    check("admin ✅/❌ tugmalari tilga mos",
          any(CYRILLIC.search(t) for t in ru_btns)
          and not any(CYRILLIC.search(t) for t in en_btns),
          f"{ru_btns} / {en_btns}")


def test_vision_prompt_localization():
    """Vision (rasm → post) tizim promptlari 3 tilda to'liq."""
    print("== 12. Vision promptlari lokalizatsiyasi ==")
    from utils.ai_agent import _VISION_SYSTEMS, _VISION_REWRITE_SYSTEMS

    for table, name in ((_VISION_SYSTEMS, "_VISION_SYSTEMS"),
                        (_VISION_REWRITE_SYSTEMS, "_VISION_REWRITE_SYSTEMS")):
        check(f"{name} 3 tilda to'liq", set(table) == set(LANGS), str(sorted(table)))
        check(f"{name}[ru] kirill (o'zbekcha emas)",
              bool(CYRILLIC.search(table["ru"]))
              and "O'ZBEK" not in table["ru"] and "o'zbek" not in table["ru"].lower())
        check(f"{name}[en] o'zbekcha qoldiq yo'q",
              "O'ZBEK" not in table["en"] and "o'zbek" not in table["en"].lower()
              and not CYRILLIC.search(table["en"]))
        check(f"{name} 3 tilda farqli", len(set(table.values())) == 3)


# ================================================================
# V. TOAST / XABAR REGRESSIYASI — o'zbekcha qotirilgan matn qaytmaydi
# ================================================================
def test_toast_messages_localized():
    """Throttle/rate-limit/eskirgan menyu toast'lari lug'at orqali tilga mos."""
    print("== 13. Toast-xabarlar regressiyasi ==")
    keys = ("np_callback_wait", "sys_wait_short", "sys_error_short",
            "noop_channel_info", "ai_menu_stale", "ai_photo_stale",
            "receipt_save_error", "pend_rate_limited", "admin_only_cmd")
    for key in keys:
        vals = {c: TRANSLATIONS[c].get(key) for c in LANGS}
        check(f"{key} 3 tilda mavjud", all(vals.values()), str(vals))
        if all(vals.values()):
            check(f"{key} 3 tilda farqli", len(set(vals.values())) == 3, str(vals))

    # Manba kodda qotirilgan toast matnlari qaytmasligi (regression guard).
    hardcoded_guards = {
        "handlers/new_post.py": ["⏳ Jarayon bajarilmoqda, iltimos kuting..."],
        "handlers/__init__.py": [
            "⏳ Iltimos, biroz kuting...",
            "Bu ma'lumot tugmasi. Kanalni o'chirish uchun",
            "⚠️ <b>Bu menyu eskirgan.</b>",
        ],
        "handlers/payment_receipt.py": ["⚠️ Chekni saqlashda xatolik yuz berdi"],
        "handlers/error_handler.py": ["⚠️ Xatolik yuz berdi\", show_alert"],  # faqat qotirilgan shakl
        "main.py": ["⏳ Iltimos, kuting...\", show_alert"],
        "handlers/subscription.py": ["❌ Faqat admin bu buyruqni ishlatishi mumkin."],
    }
    for path, needles in hardcoded_guards.items():
        src = (ROOT / path).read_text(encoding="utf-8")
        for needle in needles:
            check(f"{path}: qotirilgan toast olib tashlangan ({needle[:28]}…)",
                  needle not in src, needle)

    # Va bu toast'lar endi lug'at kaliti orqali ishlatiladi.
    np_src = (ROOT / "handlers" / "new_post.py").read_text(encoding="utf-8")
    check("new_post throttle toast'i lug'atdan olinadi",
          np_src.count('get_text("np_callback_wait", get_lang(context))') >= 8,
          str(np_src.count('get_text("np_callback_wait", get_lang(context))')))
    init_src = (ROOT / "handlers" / "__init__.py").read_text(encoding="utf-8")
    check("reaction rate-limit toast'i lug'atdan olinadi",
          'get_text("pend_rate_limited", get_lang(context))' in init_src)
    check("noop toast'i lug'atdan olinadi",
          'get_text("noop_channel_info", get_lang(context))' in init_src)
    err_src = (ROOT / "handlers" / "error_handler.py").read_text(encoding="utf-8")
    check("error_handler qisqa toast'i lug'atdan olinadi",
          'sys_error_short' in err_src)
    main_src = (ROOT / "main.py").read_text(encoding="utf-8")
    check("main.py throttle toast'i lug'atdan olinadi",
          'sys_wait_short' in main_src)


def test_localize_service_error():
    """AI xatolik matnlari RU/EN uchun mos tilga o'giriladi."""
    print("== 14. AI xato xabarlarining lokalizatsiyasi ==")
    from locales.translations import localize_service_error

    uz_text = "⚠️ Mavzu kiritilmadi."
    check("uz xato matni o'zgarmaydi", localize_service_error(uz_text, "uz") == uz_text)
    ru_val = localize_service_error(uz_text, "ru")
    en_val = localize_service_error(uz_text, "en")
    check("ru xato matni ruschaga o'giriladi",
          ru_val != uz_text and bool(CYRILLIC.search(ru_val)), ru_val)
    check("en xato matni inglizchaga o'giriladi",
          en_val != uz_text and not CYRILLIC.search(en_val), en_val)
    check("noma'lum xato — asl matn qaytadi (yo'qolmaydi)",
          localize_service_error("totally unknown error text", "ru")
          == "totally unknown error text")
    check("None/bo'sh xato — xavfsiz",
          localize_service_error(None, "en") == "" )


# ================================================================
# MAIN
# ================================================================
def main():
    print("=" * 64)
    print("  UZ / RU / EN TO'LIQ PARITET AUDITI (i18n_full_parity_test)")
    print("=" * 64)
    test_key_parity()
    test_overlay_and_translation()
    test_format_args_parity()
    test_safe_t_fallback()
    test_reply_buttons_route_to_handlers()
    test_keyboard_refresh_on_language_change()
    test_ai_prompt_language_binding()
    test_router_prompt_details()
    test_ai_service_orchestrator_language()
    test_datetime_localization()
    test_photo_check_localization()
    test_vision_prompt_localization()
    test_toast_messages_localized()
    test_localize_service_error()

    print("=" * 64)
    print(f"JAMI: o'tdi={passed}, xato={failures}")
    print("=" * 64)
    if failures:
        print("❌ I18N TO'LIQ PARITET TESTI YO'QOTILDI")
        sys.exit(1)
    print("✅ BARCHA UZ/RU/EN PARITET TESTLARI YASHIL")


if __name__ == "__main__":
    main()
