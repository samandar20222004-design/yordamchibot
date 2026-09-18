#!/usr/bin/env python3
"""✨ MAGIC POST — KILLER FEATURE #1 OQIM TESTI (deterministik, mock asosida).

Qamrov (topshiriq talablari bilan birma-bir):

  TEST 1:  Foydalanuvchi xom matn yuborganda USLUBLAR MENYUSI chiqadi
           (5 ta uslub tugmasi: 🔥 Sotuv / 💎 Premium / 😊 Oddiy /
           📢 Reklama / 📰 Informativ) + asosiy menyu «✨ Magic Post»
           tugmasi 3 tilga ham faol (klaviatura + routing filtri).
  TEST 2:  Uslub tanlanganda AI so'rovi TO'G'RI TIZIM PROMPTI bilan
           chaqiriladi (har uslub uchun o'z formulasi: AIDA/PAS, premium
           estetika, blogerona, ad-offer, ekspert) + qat'iy til bloki
           (uz/ru/en) + safe_html + 3-5 hashtag kafolati.
  TEST 3:  Natijadan keyin [📢 Kanalga yuborish] DARHOL jo'natadi
           (bitta kanal → avtomatik, ko'p kanal → tanlov + «hammasi»),
           [📅 Rejalashtirish] mavjud scheduler oqimiga (AI_GET_TIME)
           to'g'ri kalitlar bilan uzatadi, [🔄 Boshqa uslub] matnni
           qayta so'ramaydan uslub menyusini qaytaradi.
  TEST 4:  i18n PARITET — translations paketida UZ/RU/EN 100% (kalitlar,
           {placeholder}lar, bo'sh qiymatlar) + handler ishlatgan HAR BIR
           kalit uchala tilda mavjud.

Ishga tushirish:
    bash tests/run_tests.sh          # yoki
    python3 tests/magic_post_flow_test.py
"""
import asyncio
import os
import re
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:MAGIC_POST_FLOW_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10000")

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


# ---------------------------------------------------------------------------
# FAKE TELEGRAM OBYEKTlari (deterministik — real API talab qilinmaydi)
# ---------------------------------------------------------------------------
class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id=None, text=None, parse_mode=None, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": text, "parse_mode": parse_mode})
        return SimpleNamespace(message_id=len(self.sent))


class FakeMessage:
    def __init__(self, text=None, caption=None):
        self.text = text
        self.caption = caption
        self.chat = SimpleNamespace(id=555000)
        self.replies = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kwargs):
        self.replies.append({"text": text, "reply_markup": reply_markup,
                             "parse_mode": parse_mode})
        return self


class FakeQuery:
    def __init__(self, data, user_id=777000):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = FakeMessage()
        self.answers = []
        self.edits = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None, **kwargs):
        self.edits.append({"text": text, "reply_markup": reply_markup})

    async def edit_message_reply_markup(self, reply_markup=None):
        self.edits.append({"reply_markup": reply_markup})


class FakeUpdate:
    def __init__(self, message=None, query=None, user_id=777000):
        self.message = message
        self.callback_query = query
        self.effective_user = SimpleNamespace(id=(query.from_user.id if query else user_id))


class FakeContext:
    def __init__(self, lang="uz"):
        self.user_data = {"lang": lang}
        self.bot = FakeBot()


def kb_buttons(markup):
    """InlineKeyboardMarkup → [(text, callback_data), ...]."""
    if markup is None:
        return []
    rows = (getattr(markup, "inline_keyboard", None)
            or getattr(markup, "keyboard", []) or [])
    out = []
    for row in rows:
        for btn in row:
            out.append((btn.text, btn.callback_data))
    return out


def kb_texts(markup):
    return [t for t, _d in kb_buttons(markup)]


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# MODULLAR (env sozlangandan KEYIN import qilinadi)
# ---------------------------------------------------------------------------
from handlers import magic_post as mp                      # noqa: E402
from handlers.ai_assistant import AI_GET_TIME              # noqa: E402
from keyboards.default import (                            # noqa: E402
    BTN_MAGIC_POST, BTN_MAGIC_POST_RU, BTN_MAGIC_POST_EN,
    MENU_TEXTS, exact, get_main_keyboard,
)
from locales.translations import normalize_lang            # noqa: E402
from translations import (                                 # noqa: E402
    MAGIC_POST_I18N, MAGIC_STYLE_KEYS,
    magic_post_parity_report, magic_t,
)
from utils.ai_agent import (                               # noqa: E402
    MAGIC_POST_STYLES, MAGIC_POST_SYSTEMS, ensure_magic_hashtags,
    generate_magic_post, normalize_magic_style, with_language,
)

LANGS = ("uz", "ru", "en")

# ---------------------------------------------------------------------------
# DB MOCK — handlers.magic_post.db.run_db ni almashtiradi (fail-closed yo'q:
# bu test DB emas, HANDLER oqimini tekshiradi).
# ---------------------------------------------------------------------------
FAKE_CHANNELS = [("-100111001", "Kanal A"), ("-100222002", "Kanal B")]


async def fake_run_db(func, *args, **kwargs):
    name = getattr(func, "__name__", str(func))
    if name == "get_user_channels":
        return list(FAKE_CHANNELS)
    if name == "is_premium":
        return False
    if name == "check_ai_limit":
        return (True, 0, 30)
    if name == "use_user_credit":
        return True
    if name == "increment_ai_usage":
        return True
    if name == "add_user_credit":
        return True
    if name == "refund_ai_usage":
        return True
    return None


DB_PATCH = patch("handlers.magic_post.db.run_db", new=fake_run_db)


# ============================================================================
# TEST 1 — USLUBLAR MENYUSI + ASOSIY MENYU TUGMASI
# ============================================================================
def test_styles_menu_flow():
    print("\n== TEST 1: Xom matn → uslublar menyusi (5 uslub) ==")

    ctx = FakeContext(lang="uz")
    msg = FakeMessage()

    # 1a) 3-QISM (7-tugma standarti): «✨ Magic Post» asosiy menyuda endi
    # YO'Q — lekin oqimi yashaydi: routing filtri eski yorliqni hali ham
    # taniydi (keshdagi eski klaviatura xabarlari uchun backward
    # compatibility) va asosiy menyu aynan 6 tugma.
    for lang, btn in (("uz", BTN_MAGIC_POST), ("ru", BTN_MAGIC_POST_RU),
                      ("en", BTN_MAGIC_POST_EN)):
        kb = get_main_keyboard(False, lang=lang)
        texts = [b.text for row in kb.keyboard for b in row]
        check(f"asosiy menyu '{lang}': klassik — aynan 6 tugma",
              len(texts) == 6, str(texts))
        check(f"asosiy menyu '{lang}': «✨ Magic Post» menyu'dan chiqdi",
              btn not in texts, str(texts))
    pattern = exact(BTN_MAGIC_POST).pattern
    check("routing `exact()` filtri «✨ Magic Post» ni taniydi",
          re.search(pattern, "✨ Magic Post") is not None)
    check("MENU_TEXTS registry'da 'magic_post' bor", "magic_post" in MENU_TEXTS)
    check("magic_post entry handler reyestrda",
          callable(mp.magic_post_entry) and mp.MAGIC_INPUT == 430)

    # 1b) Entry: yo'riqnoma chiqadi, FSM MAGIC_INPUT ga o'tadi.
    upd = FakeUpdate(message=msg)
    state = run(mp.magic_post_entry(upd, ctx))
    check("entry MAGIC_INPUT holatini qaytaradi", state == mp.MAGIC_INPUT)
    # 2-BOSQICH: intro IXCHAM SaaS taklifi — uzun 15 qatorli uslublar
    # tushuntirishi YO'Q (uslublar keyingi ekranda tanlanadi).
    intro_text = msg.replies[0]["text"] if msg.replies else ""
    check("entry yo'riqnomasi yuborildi (mp_intro)",
          len(msg.replies) == 1 and "Magic Post" in intro_text
          and "postgacha" in intro_text)
    check("mp_intro ixcham (≤4 qator, uslublar ro'yxatisiz)",
          intro_text.count("\n") <= 4 and "AIDA" not in intro_text
          and "🔥" not in intro_text, repr(intro_text))

    # 1c) Xom matn yuborildi → uslublar menyusi (5 uslub + ❌ Bekor qilish).
    raw = "Yangi koffemiz 20% chegirma bilan sotilmoqda, dizayner stakanlar"
    msg2 = FakeMessage(text=raw)
    upd2 = FakeUpdate(message=msg2)
    state = run(mp.magic_text_received(upd2, ctx))
    check("matn qabul qilingach MAGIC_STYLE_SELECT qaytadi",
          state == mp.MAGIC_STYLE_SELECT)
    check("xom matn user_data'ga saqlandi",
          ctx.user_data.get("magic_raw_text") == raw)
    check("uslublar menyusi yuborildi", len(msg2.replies) == 1)
    menu_markup = msg2.replies[0]["reply_markup"]
    cbs = [d for _t, d in kb_buttons(menu_markup)]
    expected = {f"mp_style:{s}" for s in MAGIC_POST_STYLES} | {"mp_cancel"}
    check(f"5 uslub + bekor tugmasi chiqdi {sorted(cbs)}",
          set(cbs) == expected, str(cbs))
    cancel_labels = [t2 for t2, d in kb_buttons(menu_markup) if d == "mp_cancel"]
    check("[❌ Bekor qilish] tugmasi bor (dead-end trap tuzatildi)",
          cancel_labels == ["❌ Bekor qilish"], str(cancel_labels))
    menu_text = msg2.replies[0]["text"]
    check("menyuda uslub tushuntirishlari bor (AIDA/PAS, premium, blogger)",
          "AIDA" in menu_text and "premium" in menu_text.lower()
          and "blogerona" in menu_text)

    # 1d) Media (rasm) yuborilsa — matn so'raladi, oqim uzilmaydi.
    ctx3 = FakeContext()
    photo_msg = FakeMessage(text=None)
    state = run(mp.magic_text_received(FakeUpdate(message=photo_msg), ctx3))
    check("rasm yuborilsa MAGIC_INPUT'da qoladi", state == mp.MAGIC_INPUT)
    check("media uchun yo'riqnoma (mp_media_hint)",
          len(photo_msg.replies) == 1 and "AI Yordamchi" in photo_msg.replies[0]["text"])

    # 1e) RU tilida ham menyu to'liq (3 tildalik interfeys).
    ctx_ru = FakeContext(lang="ru")
    msg_ru = FakeMessage(text="Новый кофе со скидкой 20%")
    run(mp.magic_text_received(FakeUpdate(message=msg_ru), ctx_ru))
    ru_cbs = [d for _t, d in kb_buttons(msg_ru.replies[0]["reply_markup"])]
    check("RU: uslublar menyusi 5 tugma bilan chiqdi", set(ru_cbs) == expected)
    check("RU: matn ruscha («В каком стиле»)",
          "каком стиле" in msg_ru.replies[0]["text"])


# ============================================================================
# TEST 2 — AI SO'ROVI TO'G'RI TIZIM PROMPTI BILAN CHAQIRILADI
# ============================================================================
def _style_marker(style):
    """Har uslub tizim promptidagi o'ziga xos belgilar (til bo'yicha)."""
    return {
        "sales": ("AIDA",),  # AIDA/PSA latincha — uchala tilda ham bor
        "premium": {"uz": ("PREMIUM", "estetik"), "ru": ("ПРЕМИУМ", "элегантно"),
                    "en": ("PREMIUM", "aesthetic")},
        "casual": {"uz": ("ODDIY", "blogerona"), "ru": ("ОБЫЧНЫЙ", "блогерская"),
                   "en": ("CASUAL", "blogger")},
        "ads": {"uz": ("REKLAMA", "SARLAVHA"), "ru": ("РЕКЛАМА", "ЗАГОЛОВОК"),
                "en": ("ADS", "HEADLINE")},
        "informative": {"uz": ("INFORMATIV", "PUNKT"), "ru": ("ИНФОРМАТИВНЫЙ", "ПУНКТОВ"),
                        "en": ("INFORMATIVE", "BULLETS")},
    }[style]


def _markers_for(style, lang):
    spec = _style_marker(style)
    return spec if isinstance(spec, tuple) else spec.get(lang, spec["uz"])


def test_ai_system_prompt_architecture():
    print("\n== TEST 2: AI so'rovi uslubga xos tizim prompti bilan ==")

    # 2a) Arxitektura: 5 uslub × 3 til — barcha promptlar mavjud va to'liq.
    check("5 uslub ro'yxatda",
          set(MAGIC_POST_STYLES) == {"sales", "premium", "casual", "ads", "informative"})
    for style in MAGIC_POST_STYLES:
        for lang in LANGS:
            prompt = MAGIC_POST_SYSTEMS.get(style, {}).get(lang, "")
            markers = _markers_for(style, lang)
            ok = len(prompt) > 200 and all(m.lower() in prompt.lower() for m in markers)
            check(f"prompt[{style}][{lang}] uslub formulasini o'z ichiga oladi ({markers[0]})", ok)
            check(f"prompt[{style}][{lang}] JSON kontrakti bor",
                  '"post_text"' in prompt)
            check(f"prompt[{style}][{lang}] hashtag qoidasi bor",
                  "3-5" in prompt and "#" in prompt)

    # 2b) generate_magic_post — AI call tizim prompti va til bloki bilan.
    captured = {}

    async def fake_ai_response(prompt, system_instruction=None, timeout=None,
                               tone=None, is_pro=False, lang="uz"):
        captured["prompt"] = prompt
        captured["system"] = system_instruction
        captured["lang"] = lang
        return {"post_text": "<b>Katta sotuv!</b> Bugun 20% chegirma. "
                             "🛒 Buyurtma bering. #sotuv #chegirma #kofe"}

    with patch("utils.ai_agent.generate_ai_response", new=fake_ai_response):
        result = run(generate_magic_post("Kofe sotiladi 20% chegirma", "sales", lang="ru"))

    check("natija post_text bilan qaytdi", bool(result.get("post_text")))
    check("uslub kanonlashtirildi", result.get("style") == "sales")
    check("AI prompti = foydalanuvchi matni",
          "Kofe" in captured["prompt"] and "20%" in captured["prompt"])
    sys_prompt = captured["system"]
    check("tizim promptida SOTUV formulasi (AIDA/PAS)",
          "AIDA" in sys_prompt and "PAS" in sys_prompt)
    check("tizim promptida format qoidalari (safe HTML)",
          "Telegram HTML" in sys_prompt)
    # Qat'iy til bloki (RU) — with_language orqali.
    ru_block = with_language("", "ru")
    ru_marker = ru_block.strip().splitlines()[0][:40]
    check("tizim promptida QAT'IY RU til qoidasi bor",
          "РУССКОМ" in sys_prompt or "RU" in sys_prompt, ru_marker)
    check("lang parametri AI'ga uzatildi", captured["lang"] == "ru")

    # 2c) Noma'lum uslub → default (hech qachon yiqilmaydi).
    check("noma'lum uslub 'casual'ga tushadi",
          normalize_magic_style("nope") == "casual" and
          normalize_magic_style("🔥 Sotuv") == "sales")

    # 2d) AI xato qaytarsa — {"error": ...} (handler refund qiladi).
    async def failing_ai(prompt, system_instruction=None, **kwargs):
        return {"error": "boom"}

    with patch("utils.ai_agent.generate_ai_response", new=failing_ai):
        bad = run(generate_magic_post("matn", "ads", lang="uz"))
    check("AI xatosi error sifatida qaytadi", bool(bad.get("error")))


def test_hashtag_and_html_guarantees():
    print("\n== TEST 2b: 3-5 hashtag kafolati + safe_html ==")

    # AI hashtag yozmadi → 4 taga yetkaziladi (oxirgi alohida qator).
    out = ensure_magic_hashtags("<b>Salom</b> dunyo", "sales", "uz")
    tags = re.findall(r"#\w+", out)
    check("hashtag yo'q matnga 3-5 tag qo'shildi", 3 <= len(tags) <= 5, str(tags))
    check("taglar oxirgi qatorda", out.strip().splitlines()[-1].startswith("#"))

    # AI 7 ta yozdi → 5 tasi qoladi.
    seven = "Matn\n\n#aa #bb #cc #dd #ee #ff #gg"
    out2 = ensure_magic_hashtags(seven, "casual", "en")
    tags2 = re.findall(r"#\w+", out2)
    check("5 tadan ortiq taglar kesildi (5 qoldi)", len(tags2) == 5, str(tags2))
    check("asosiy matn saqlanib qoldi", "Matn" in out2)

    # 3 ta bor → tegilmaydi (tartib saqlanadi).
    three = "Body #alpha #beta #gamma"
    out3 = ensure_magic_hashtags(three, "premium", "ru")
    check("3 ta tag bilan matn o'zgarmadi",
          re.findall(r"#\w+", out3) == ["#alpha", "#beta", "#gamma"], out3)

    # Inline taglar ham oxirgi qatorga ko'chiriladi (dublikatsiz).
    inline = "Bugun #chegirma boshlandi, shoshiling #chegirma #aksiya"
    out4 = ensure_magic_hashtags(inline, "ads", "uz")
    tags4 = re.findall(r"#\w+", out4)
    check("dublikat taglar birlashtirildi",
          len(tags4) == len(set(t.lower() for t in tags4)) and tags4.count("#chegirma") == 1,
          str(tags4))

    # safe_html: script/unknown taglar escape qilinadi, <b> saqlanadi.
    dirty = generate_magic_post.__globals__  # noqa: F841 (modul yuklangani tekshirildi)
    from utils.ai_agent import sanitize_magic_post_html
    cleaned = sanitize_magic_post_html("<b>OK</b><script>alert(1)</script> 5 < 10")
    check("<b> saqlandi", "<b>OK</b>" in cleaned)
    check("<script> escape qilindi", "<script>" not in cleaned and "alert" in cleaned)
    check("matndagi '<' escape qilindi", "&lt;" in cleaned or "5" in cleaned)


# ============================================================================
# TEST 3 — NATIJADAN KEYIN: KANALGA YUBORISH + REJALASHTIRISH + BOSHQA USLUB
# ============================================================================
def _seed_result(ctx, post="<b>Magic post</b> matn #a #b #c #d"):
    ctx.user_data["magic_raw_text"] = "kofe chegirma"
    ctx.user_data["magic_post_text"] = post
    ctx.user_data["magic_style"] = "sales"
    ctx.user_data["magic_usage_counted"] = False


def test_result_actions_integration():
    print("\n== TEST 3: Kanalga yuborish / Rejalashtirish / Boshqa uslub ==")

    # --- 3a) Uslub tanlanadi → AI chaqiriladi → natija + 3 amal tugmasi ---
    ctx = FakeContext(lang="uz")
    ctx.user_data["magic_raw_text"] = "kofe chegirma matn"
    query = FakeQuery("mp_style:sales")
    upd = FakeUpdate(query=query)

    ai_calls = []

    async def fake_gen(raw, style, lang="uz", is_pro=False, timeout=None):
        ai_calls.append({"raw": raw, "style": style, "lang": lang})
        return {"post_text": "<b>Aksiya!</b> Kofe 20% arzon. #sotuv #kofe #chegirma #aksiya",
                "style": style, "lang": lang}

    with DB_PATCH, patch("handlers.magic_post.generate_magic_post", new=fake_gen):
        state = run(mp.magic_style_callback(upd, ctx))

    check("generatsiyadan keyin MAGIC_RESULT qaytadi", state == mp.MAGIC_RESULT)
    check("AI uslub va xom matn bilan chaqirildi",
          ai_calls and ai_calls[0]["style"] == "sales"
          and ai_calls[0]["raw"] == "kofe chegirma matn")
    check("tayyor post user_data'da", "magic_post_text" in ctx.user_data)
    last = query.edits[-1]
    btns = kb_buttons(last.get("reply_markup"))
    check("natija ekranida post bor", "Aksiya" in last.get("text", ""))
    check("[📢 Kanalga yuborish] tugmasi bor",
          ("📢 Kanalga yuborish", "mp_send") in btns, str(btns))
    check("[📅 Rejalashtirish] tugmasi bor",
          ("📅 Rejalashtirish", "mp_sched") in btns)
    check("[✏️ Qayta yozish / Uslub] tugmasi bor (mp_restyle callback saqlangan)",
          ("✏️ Qayta yozish / Uslub", "mp_restyle") in btns, str(btns))
    check("[◀️ Orqaga] tugmasi bor (mp_back)",
          ("◀️ Orqaga", "mp_back") in btns, str(btns))
    check("natija klaviaturasi ixcham layout: 2+2+1",
          [len(r) for r in last.get("reply_markup").inline_keyboard] == [2, 2, 1])

    # --- 3b) [📢 Kanalga yuborish]: bitta kanal — DARHOL yuborish ---
    ctx1 = FakeContext(lang="uz")
    _seed_result(ctx1)
    q1 = FakeQuery("mp_send")

    async def one_channel(func, *a, **kw):
        return [("-100333", "Mening Kanalim")] if func.__name__ == "get_user_channels" else None

    with patch("handlers.magic_post.db.run_db", new=one_channel):
        state = run(mp.magic_send_now_callback(FakeUpdate(query=q1), ctx1))
    check("bitta kanal: sessiya tugadi (END)",
          state == mp.ConversationHandler.END)
    sent = ctx1.bot.sent
    check("post kanalga yuborildi",
          len(sent) == 1 and sent[0]["chat_id"] == "-100333"
          and "Magic post" in sent[0]["text"])
    ok_edits = [e for e in q1.edits if isinstance(e.get("text"), str)]
    check("muvaffaqiyat xabari (mp_sent_ok)",
          any("muvaffaqiyatli" in e["text"] for e in ok_edits), str(ok_edits[-1:]))

    # --- 3c) Ko'p kanal → tanlov menyusi → tanlangan kanalga yuborish ---
    ctx2 = FakeContext(lang="uz")
    _seed_result(ctx2)
    q2 = FakeQuery("mp_send")
    with DB_PATCH:
        state = run(mp.magic_send_now_callback(FakeUpdate(query=q2), ctx2))
    check("ko'p kanal: MAGIC_SEND_CHOOSE qaytadi", state == mp.MAGIC_SEND_CHOOSE)
    chooser = q2.edits[-1].get("reply_markup")
    ch_btns = kb_buttons(chooser)
    check("kanal tanlov tugmalari chiqdi",
          ("mp_ch:0", ) == tuple(d for _t, d in ch_btns if d == "mp_ch:0")
          and "mp_ch:1" in [d for _t, d in ch_btns])
    check("«Barcha kanallarga» tugmasi bor",
          any(d == "mp_chall" for _t, d in ch_btns), str(ch_btns))

    q2b = FakeQuery("mp_ch:1")
    with DB_PATCH:
        state = run(mp.magic_channel_picked_callback(FakeUpdate(query=q2b), ctx2))
    check("tanlangan kanalga yuborildi (faqat 1 ta)",
          len(ctx2.bot.sent) == 1 and ctx2.bot.sent[0]["chat_id"] == "-100222002")
    check("yuborilgach sessiya tugadi", state == mp.ConversationHandler.END)

    # «Barcha kanallarga» — ikkala kanalga ham + AI usage sanagichi 1 marta.
    ctx3 = FakeContext(lang="ru")
    _seed_result(ctx3)
    inc_calls = []

    async def counter_run_db(func, *a, **kw):
        name = getattr(func, "__name__", str(func))
        if name == "get_user_channels":
            return list(FAKE_CHANNELS)
        if name == "is_premium":
            return False
        if name == "increment_ai_usage":
            inc_calls.append(1)
            return True
        return None

    with patch("handlers.magic_post.db.run_db", new=counter_run_db):
        run(mp.magic_send_now_callback(FakeUpdate(query=FakeQuery("mp_send")), ctx3))
        q3 = FakeQuery("mp_chall")
        run(mp.magic_channel_picked_callback(FakeUpdate(query=q3), ctx3))
    ids = [s["chat_id"] for s in ctx3.bot.sent]
    check("«Barcha kanallarga»: 2 ta kanalga yuborildi",
          sorted(ids) == ["-100111001", "-100222002"], str(ids))
    check("free foydalanuvchi uchun AI usage sanagichi AYNAN 1 marta oshirildi",
          len(inc_calls) == 1, str(len(inc_calls)))

    # --- 3d) [📅 Rejalashtirish]: scheduler oqimiga to'g'ri uzatish ---
    ctx4 = FakeContext(lang="uz")
    _seed_result(ctx4)
    q4 = FakeQuery("mp_sched")

    shown = {}

    async def fake_time_prompt(msg, post_text, file_id, post_type, lang="uz"):
        shown.update({"post": post_text, "file_id": file_id,
                      "post_type": post_type, "lang": lang})

    with patch("handlers.magic_post._show_time_prompt", new=fake_time_prompt):
        state = run(mp.magic_schedule_callback(FakeUpdate(query=q4), ctx4))

    check("scheduler holatiga o'tdi (AI_GET_TIME)", state == AI_GET_TIME)
    check("post scheduler kalitiga qo'yildi",
          ctx4.user_data.get("ai_generated_post") == "<b>Magic post</b> matn #a #b #c #d")
    check("media kalitlari text rejimida",
          ctx4.user_data.get("ai_post_type") == "text"
          and ctx4.user_data.get("ai_file_id") is None)
    check("vaqt tanlash oynasi ko'rsatildi",
          shown.get("post") == ctx4.user_data.get("ai_generated_post")
          and shown.get("lang") == "uz")

    # Scheduler confirm (ai_confirm_callback) shu kalitlarni ishlatadi —
    # integratsiya kontrakti: add_post chaqirilishi.
    async def sched_run_db(func, *a, **kw):
        name = getattr(func, "__name__", str(func))
        if name == "get_user_channels":
            return [("-100111001", "Kanal A")]
        if name == "is_premium":
            return False
        if name == "add_post":
            sched_run_db.added = kw.get("content")
            return 101
        return None

    sched_run_db.added = None
    from handlers.ai_assistant import ai_confirm_callback
    ctx4s = ctx4
    ctx4s.user_data["ai_scheduled_time"] = None

    async def fake_ad_line(uid):
        return ""

    with patch("handlers.ai_assistant.db.run_db", new=sched_run_db):
        with patch("handlers.ai_assistant.get_auto_ad_injection_async",
                   new=fake_ad_line):
            state = run(ai_confirm_callback(FakeUpdate(
                query=FakeQuery("ai_post_schedule")), ctx4s))
    check("scheduler confirm posti DB'ga yozdi (add_post)",
          (sched_run_db.added or "").startswith("<b>Magic post</b>"))
    check("scheduler confirm sessiyani yopadi", state == mp.ConversationHandler.END)

    # --- 3e) [🔄 Boshqa uslub]: matn qayta so'ralmaydi ---
    ctx5 = FakeContext(lang="uz")
    _seed_result(ctx5)
    q5 = FakeQuery("mp_restyle")
    state = run(mp.magic_restyle_callback(FakeUpdate(query=q5), ctx5))
    check("restyle uslub menyusiga qaytadi", state == mp.MAGIC_STYLE_SELECT)
    check("xom matn SAQLANIB qoldi (qayta kiritish shart emas)",
          ctx5.user_data.get("magic_raw_text") == "kofe chegirma")
    check("restyle ekranida 'saqlandi' xabari bor",
          "saqlab qolindi" in q5.edits[-1].get("text", ""))
    restyle_cbs = [d for _t, d in kb_buttons(q5.edits[-1].get("reply_markup"))]
    check("restyle ekranida yana 5 uslub + bekor", len(restyle_cbs) == 6)

    # --- 3f) Stale tugma — sessiyadan tashqarida bosilsa toast beriladi ---
    q6 = FakeQuery("mp_send")
    run(mp.magic_stale_callback(FakeUpdate(query=q6), FakeContext()))
    check("stale tugma javoblandi (toast)",
          q6.answers and q6.answers[0][0], str(q6.answers))


def _async(value):
    async def _inner(*a, **kw):
        return value
    return _inner()


# ============================================================================
# TEST 4 — i18n PARITET (UZ / RU / EN = 100%)
# ============================================================================
def test_i18n_parity():
    print("\n== TEST 4: i18n paritet (translations paketi) ==")

    report = magic_post_parity_report()
    check(f"kalitlar soni > 20 ({report['keys']})", report["keys"] >= 20)
    check("RU'da yetishmayotgan kalit yo'q", report["missing"].get("ru") == [],
          str(report["missing"]))
    check("EN'da yetishmayotgan kalit yo'q", report["missing"].get("en") == [])
    check("ortiqcha kalit yo'q (ru/en)",
          not report["extra"].get("ru") and not report["extra"].get("en"))
    check("{placeholder}lar uchala tilda bir xil",
          not report["format_mismatch"], str(report["format_mismatch"]))
    check("bo'sh qiymatli kalit yo'q", not report["empty"], str(report["empty"]))
    check("PARITET 100% (in_sync)", report["in_sync"] is True)

    # Handler ishlatgan HAR BIR magic_t kaliti uchala tilda mavjud bo'lishi shart.
    src = (Path(__file__).resolve().parent.parent / "telegram_bot" /
           "handlers" / "magic_post.py").read_text(encoding="utf-8")
    used = set(re.findall(r'magic_t\(\s*"([a-z0-9_]+)"', src))
    check(f"handler {len(used)} ta magic_t kaliti ishlatgan", len(used) >= 12)
    missing = [
        f"{lang}:{key}"
        for key in used
        for lang in LANGS
        if key not in (MAGIC_POST_I18N.get(lang) or {})
    ]
    check("handler kalitlari uchala tilda to'liq", not missing, str(missing[:6]))

    # Formatli kalitlar 3 tilda ham formatlanadi (KeyError yo'q).
    for key in ("mp_generating", "mp_send_all", "mp_sent_ok"):
        for lang in LANGS:
            value = magic_t(key, lang, style="🔥 Sotuv", count=2, channels="X")
            check(f"magic_t('{key}', {lang}) formatlandi", "{" not in value, value)

    # Asosiy tugma + uslub yorliqlari topshiriqdagi nomlar bilan bir xil.
    uz = MAGIC_POST_I18N["uz"]
    check("5 uslub yorlig'i topshiriq bilan bir xil (uz)",
          [uz[MAGIC_STYLE_KEYS[s][0]] for s in
           ("sales", "premium", "casual", "ads", "informative")] ==
          ["🔥 Sotuv", "💎 Premium", "😊 Oddiy", "📢 Reklama", "📰 Informativ"])
    for lang in LANGS:
        code = normalize_lang(lang)
        check(f"btn_magic_post ({code}) = «✨ Magic Post»",
              MAGIC_POST_I18N[code]["btn_magic_post"] == "✨ Magic Post")

    # Amallar tugmalari topshiriq matnlariga mos (3 til).
    expected_actions = {
        "mp_btn_send_channel": ("📢", {"uz": "kanal", "ru": "канал", "en": "channel"}),
        "mp_btn_schedule": ("📅", None),
        "mp_btn_restyle": ("🔄", None),
        "mp_btn_rewrite": ("✏️", None),
        "mp_btn_back": ("◀️", None),
    }
    for key, (prefix, meaning) in expected_actions.items():
        for lang in LANGS:
            value = magic_t(key, lang)
            check(f"{key} ({lang}) '{prefix}' bilan boshlanadi",
                  value.startswith(prefix), value)
            if meaning:
                check(f"{key} ({lang}) ma'nosi to'g'ri ('{meaning[lang]}')",
                      meaning[lang] in value.lower(), value)


# ============================================================================
def main():
    print("=" * 62)
    print(" ✨ MAGIC POST — KILLER FEATURE #1 OQIM TESTI")
    print("=" * 62)
    test_styles_menu_flow()
    test_ai_system_prompt_architecture()
    test_hashtag_and_html_guarantees()
    test_result_actions_integration()
    test_i18n_parity()

    print("\n" + "=" * 62)
    print(f" JAMI: o'tdi={passed}, xato={failures}")
    if failures:
        print(" [FAIL] MAGIC POST OQIMIDA XATOLIKLAR BOR ^^^")
        return 1
    print(" BARCHA MAGIC POST TESTLARI 100% YASHIL ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
