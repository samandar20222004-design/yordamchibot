#!/usr/bin/env python3
"""🧭 3-QADAM (POSTASSIST UI/UX POLISH) — MAVZU ANIQLIGI, FORMAT VA SIFAT TESTI.

Muammo (foydalanuvchi reporti): "yangiliklar" yoki "sport" deb 1 ta so'z
yozilganda bot nima haqidaligini so'ramay, darhol quruq va umumiy gaplar
to'qirdi; "yangiliklar" mavzusi xato ravishda "🛒 Sotuv" deb olinib, kanal
a'zoligi haqida reklama yozilardi.

Ushbu test quyidagilarni QAT'IY kafolatlaydi:

  TEST 1 — ANIQLASHTIRISH TRIGGERI: qisqa (< 3 so'z) yoki umumiy mavzu
           ("sport", "yangiliklar", "biznes", "sport haqida bo'lsin ...")
           → wizard talab qilinadi; aniq/batafsil mavzu → eski yo'l.
  TEST 2 — FORMAT AJRATISH: "yangilik/xabar/sport/voqea" → 📰 news va HECH
           QACHON 🛒 sales (hatto sotuv so'zi yonma-yon bo'lsa ham);
           "sotiladi/narxi/aksiya" → sales; maslahat/tahlil → tips;
           qisqa/fakt → short; axborot formatlari Magic "sales"/"ads"
           uslubiga tushmaydi.
  TEST 3 — SOTUV PARAMETRLARI: 🛒 tanlansa yoki tafsilotsiz sotuv mavzusi
           bo'lsa → mahsulot nomi/narxi/xususiyati so'rovi (spetsifikatsiya
           matni aynan); tafsilotli sotuv mavzusi to'silmaydi.
  TEST 4 — WIZARD UI: "📌 Qaysi yo'nalish ..." savoli aynan; 5 tugma
           (📰/💡/🔥/🛒/✍️) yorliq + callback'lar aynan; 2+2+1 layout;
           64-bayt xavfsizlik; uz/ru/en paritet.
  TEST 5 — HANDLER INTEGRATSIYA: Magic Post'da "sport" → CLARIFY + wizard
           klaviatura; batafsil mavzu → STYLE_SELECT (regressiya yo'q);
           format callback'lar → to'g'ri holat + to'g'ri matn; sotuv/aniq
           matn qabul → STYLE_SELECT + birlashgan mavzu; takroriy "sport"
           cheksiz siklga tushmaydi; stale xavfsiz; AI Studio'da "sport"
           generatsiyasiz CLARIFY'ga o'tadi (kvota bron qilinmaydi).
  TEST 6 — FLUFF-GUARD: "Kanalga obuna bo'ling", "Bizning kanal eng
           ishonchli manba", "Har kuni siz uchun saralab olamiz" kabi quruq
           shablonlar BARCHA generatsiya promptlarida yo'q; sifat standartida
           Hook + <b>/<i> + • ro'yxatlar + aniq mazmun talablari bor.
  TEST 7 — FSM XAVFSIZLIK + REGRESSIYA: 434/435/436 holatlar noyob va
           ConversationHandler'da ro'yxatda; Phase A-E xavfsizlik filtrlari
           (mock siyosati, validator, DNA, avtopilot/dublikat, team) joyida.

Ishga tushirish:
    PYTHON=/tmp/venv/bin/python bash tests/run_tests.sh   # yoki
    python3 tests/ai_clarification_and_intent_test.py
"""

import asyncio
import os
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:AI_CLARIFICATION_TOKEN")
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
# FAKE TELEGRAM OBYEKTLARI (deterministik — real API talab qilinmaydi)
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
        self.chat_id = 555000
        self.from_user = SimpleNamespace(id=777000)
        self.media_group_id = None
        self.photo = None
        self.video = None
        self.document = None
        self.audio = None
        self.animation = None
        self.voice = None
        self.sticker = None
        self.replies = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kwargs):
        self.replies.append({"text": text, "reply_markup": reply_markup,
                             "parse_mode": parse_mode})
        return self

    async def reply_photo(self, *args, **kwargs):  # pragma: no cover
        return self

    async def delete(self):  # pragma: no cover
        return True


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


def kb_rows(markup):
    if markup is None:
        return []
    return [len(row) for row in (getattr(markup, "inline_keyboard", None) or [])]


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# MODULLAR (env sozlangandan KEYIN import qilinadi)
# ---------------------------------------------------------------------------
from handlers import ai_post as aip                       # noqa: E402
from handlers import magic_post as mp                     # noqa: E402
from handlers import ai_assistant as ai                   # noqa: E402
from keyboards.callback_data import (                     # noqa: E402
    CALLBACK_DATA_MAX_BYTES, is_callback_safe,
)
from services.ai.prompts import (                         # noqa: E402
    FORBIDDEN_FLUFF_PHRASES, FORMAT_SYSTEMS, QUALITY_RULES,
    build_format_system, detect_post_format, format_hint_line,
    has_concrete_details, is_sales_topic, map_format_to_magic_style,
    needs_clarification, scan_text_for_fluff, should_ask_sales_params,
)
from utils.ai_agent import (                              # noqa: E402
    MAGIC_POST_STYLES, MAGIC_POST_SYSTEMS,
)

LANGS = ("uz", "ru", "en")

# Spetsifikatsiya matnlari (aynan mos kelishi shart).
SPEC_CLARIFY_UZ = "📌 Qaysi yo'nalish bo'yicha post tayyorlaymiz?"
SPEC_SALES_UZ = (
    "Nimani sotyapmiz? Iltimos, mahsulot nomi, narxi va asosiy "
    "xususiyatini yozing (Masalan: Erkaklar krossovkasi, 250 000 "
    "so'm, yetkazib berish bepul)."
)
SPEC_BUTTONS_UZ = [
    ("📰 Yangiliklar / Voqea", "aip_fmt:news"),
    ("💡 Maslahat / Tahlil", "aip_fmt:tips"),
    ("🔥 Qisqa / Faktlar", "aip_fmt:short"),
    ("🛒 Mahsulot / Sotuv", "aip_fmt:sales"),
    ("✍️ O'zim aniq yozaman", "aip_fmt:custom"),
]


# ===========================================================================
# TEST 1 — ANIQLASHTIRISH TRIGGERI
# ===========================================================================
def test_clarification_trigger():
    print("\n== TEST 1: Qisqa/umumiy mavzu → wizard, aniq mavzu → eski yo'l ==")

    short_topics = [
        "sport", "yangiliklar", "yangilik", "biznes", "futbol",
        "xabar", "biznes haqida", "sport yangiliklari",
        "новости", "спорт", "бизнес",
        "news", "sport", "business",
        "krossovka sotiladi", "aksiya", "chegirma",
    ]
    for topic in short_topics:
        check(f"«{topic}» → aniqlashtirish talab qilinadi",
              needs_clarification(topic) is True)

    # Uzun, lekin mazmuni faqat umumiy so'zlardan iborat mavzu.
    check("«sport haqida bo'lsin futbol bo'yicha» → wizard",
          needs_clarification("sport haqida bo'lsin futbol bo'yicha") is True)
    check("bo'sh mavzu → wizard", needs_clarification("   ") is True)

    detailed = [
        "Yangi koffemiz 20% chegirma bilan sotilmoqda, dizayner stakanlar",
        "Talabalar uchun ertalabki sportning 5 foydasi haqida post",
        "Новый кофе со скидкой 20%",
        "How to brew perfect coffee at home every morning",
    ]
    for topic in detailed:
        check(f"aniq mavzu to'silmaydi: «{topic[:40]}…»",
              needs_clarification(topic) is False, repr(topic))


# ===========================================================================
# TEST 2 — FORMAT AJRATISH (yangiliklar HECH QACHON sotuv emas)
# ===========================================================================
def test_format_detection():
    print("\n== TEST 2: Format ajratish — INFO ustuvorligi qat'iy ==")

    info_topics = [
        "yangiliklar", "yangilik", "sport", "xabar", "voqea",
        "bugungi sport yangiliklari", "Sport voqealari tahlili",
        "новости спорта", "свежие новости", "sport news",
    ]
    for topic in info_topics:
        fmt = detect_post_format(topic)
        check(f"«{topic}» → news (sotuv EMAS)", fmt == "news", fmt)
        check(f"«{topic}» → is_sales_topic False",
              is_sales_topic(topic) is False)

    # Sotuv so'zi yonma-yon bo'lsa ham — INFO ustun keladi.
    check("«yangiliklar aksiya» → news (INFO ustuvor)",
          detect_post_format("yangiliklar aksiya") == "news")
    check("«sport kiyimlari chegirma» → news (INFO ustuvor)",
          detect_post_format("sport kiyimlari chegirma") == "news")

    sales_topics = [
        "krossovka sotiladi", "narxi 250 ming", "katta aksiya",
        "chegirma e'lon qilindi", "buyurtma bering",
        "продаётся товар", "скидки до 50%", "sale prices today",
    ]
    for topic in sales_topics:
        fmt = detect_post_format(topic)
        check(f"«{topic}» → sales", fmt == "sales", fmt)

    check("maslahat → tips", detect_post_format("biznes maslahat kerak") == "tips")
    check("tahlil → tips", detect_post_format("bozor tahlili chuqur") == "tips")
    check("qisqa fakt → short", detect_post_format("qisqa faktlar to'plami") == "short")
    check("faktlar → short", detect_post_format("kun faktlari sarflanishi") == "short")
    check("nomalum mavzu → general",
          detect_post_format("qahva tayyorlash sirlari oshxonada") == "general")

    # Axborot formatlari Magic sotuv uslublariga tushmaydi.
    for fmt, expect in (("news", "informative"), ("tips", "informative"),
                        ("short", "casual"), ("sales", "sales")):
        style = map_format_to_magic_style(fmt)
        check(f"wizard «{fmt}» → magic «{expect}»", style == expect, style)
    for fmt in ("news", "tips", "short"):
        check(f"«{fmt}» sales/ads uslubiga tushmaydi",
              map_format_to_magic_style(fmt) not in ("sales", "ads"))
    check("noma'lum format → xavfsiz default",
          map_format_to_magic_style("nope") == "casual")


# ===========================================================================
# TEST 3 — SOTUV PARAMETRLARI SO'ROVI
# ===========================================================================
def test_sales_params_flow():
    print("\n== TEST 3: Sotuvda mahsulotsiz post to'qilmaydi ==")

    check("«krossovka sotiladi» → parametrlar so'raladi",
          should_ask_sales_params("krossovka sotiladi") is True)
    check("«aksiya» → parametrlar so'raladi",
          should_ask_sales_params("aksiya") is True)
    check("«narxi qancha» → parametrlar so'raladi",
          should_ask_sales_params("narxi qancha") is True)
    check("«yangiliklar» → parametr so'ralmaydi (sotuv emas)",
          should_ask_sales_params("yangiliklar") is False)
    check("«sport» → parametr so'ralmaydi (sotuv emas)",
          should_ask_sales_params("sport") is False)
    # Tafsilotli sotuv mavzusi to'silmaydi (raqam/narx bor).
    check("tafsilotli sotuv to'silmaydi (20% ...)",
          should_ask_sales_params(
              "Yangi koffemiz 20% chegirma bilan sotilmoqda, dizayner stakanlar"
          ) is False)
    check("«Krossovka 250 000 so'm sotiladi» to'silmaydi",
          should_ask_sales_params("Krossovka 250 000 so'mga sotiladi tezda") is False)

    check("tafsilot: raqam bor", has_concrete_details("narxi 250 ming") is True)
    check("tafsilot: yo'q", has_concrete_details("krossovka sotiladi") is False)

    # Spetsifikatsiya matni aynan.
    check("sotuv so'rovi matni spetsifikatsiyaga aynan mos",
          aip.sales_params_text("uz") == SPEC_SALES_UZ,
          repr(aip.sales_params_text("uz")))
    for lang in LANGS:
        text = aip.sales_params_text(lang)
        check(f"sotuv so'rovi [{lang}] bo'sh emas va mahsulot/narx so'raydi",
              bool(text) and len(text) > 40, text[:50])

    # 🛒 callback → parametr so'rovi + SALES_INPUT holati.
    ctx = FakeContext(lang="uz")
    ctx.user_data["aip_topic"] = "krossovka"
    ctx.user_data["aip_origin"] = "magic"
    query = FakeQuery("aip_fmt:sales")
    state = run(aip.ai_post_format_callback(FakeUpdate(query=query), ctx))
    check("🛒 bosilganda AI_POST_SALES_INPUT qaytadi",
          state == aip.AI_POST_SALES_INPUT, str(state))
    check("callback BOSHIDA answer chaqirilgan", len(query.answers) >= 1)
    edit_text = query.edits[-1].get("text", "") if query.edits else ""
    check("parametr so'rovi matni ko'rsatildi", SPEC_SALES_UZ in edit_text,
          edit_text[:80])
    check("format=sales saqlandi",
          ctx.user_data.get("aip_format") == "sales")


# ===========================================================================
# TEST 4 — WIZARD UI (savol + 5 tugma + paritet)
# ===========================================================================
def test_wizard_ui():
    print("\n== TEST 4: Wizard UI — savol, tugmalar, layout, xavfsizlik ==")

    check("savol matni spetsifikatsiyaga aynan mos",
          aip.clarification_text("uz") == SPEC_CLARIFY_UZ,
          repr(aip.clarification_text("uz")))

    buttons = aip.clarification_keyboard_buttons("uz")
    check("5 ta tugma chiqadi", len(buttons) == 5, str(buttons))
    for (exp_label, exp_cb), (label, cb_data) in zip(SPEC_BUTTONS_UZ, buttons):
        check(f"tugma «{exp_label}»", label == exp_label and cb_data == exp_cb,
              f"{label!r} / {cb_data!r}")

    markup = aip.build_clarification_keyboard("uz")
    check("layout 2+2+1", kb_rows(markup) == [2, 2, 1], str(kb_rows(markup)))

    for lang in LANGS:
        for label, cb_data in aip.clarification_keyboard_buttons(lang):
            size = len(cb_data.encode("utf-8"))
            check(f"callback [{lang}] «{cb_data}» ≤64 bayt",
                  size <= CALLBACK_DATA_MAX_BYTES and is_callback_safe(cb_data),
                  str(size))
        check(f"savol [{lang}] bo'sh emas", bool(aip.clarification_text(lang)))
    labels_uz = [t for t, _ in aip.clarification_keyboard_buttons("uz")]
    labels_ru = [t for t, _ in aip.clarification_keyboard_buttons("ru")]
    labels_en = [t for t, _ in aip.clarification_keyboard_buttons("en")]
    check("uz/ru/en tugmalar farqli (tarjima)",
          len({tuple(labels_uz), tuple(labels_ru), tuple(labels_en)}) == 3)
    # Har bir tilda 5 tasi ham noyob.
    for lang, labels in (("uz", labels_uz), ("ru", labels_ru), ("en", labels_en)):
        check(f"tugmalar [{lang}] takrorlanmaydi", len(set(labels)) == 5)


# ===========================================================================
# TEST 5 — HANDLER INTEGRATSIYA (Magic + Studio, regressiyasiz)
# ===========================================================================
async def _fake_run_db(func, *args, **kwargs):
    name = getattr(func, "__name__", str(func))
    if name == "get_user_channels":
        return [("-100111001", "Kanal A")]
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


def test_handler_integration():
    print("\n== TEST 5: Handler integratsiya — Magic + Studio ==")

    # 5a) Magic Post'da "sport" → CLARIFY + wizard klaviatura (generatsiya YO'Q).
    ctx = FakeContext(lang="uz")
    msg = FakeMessage(text="sport")
    state = run(mp.magic_text_received(FakeUpdate(message=msg), ctx))
    check("Magic «sport» → AI_POST_CLARIFY", state == aip.AI_POST_CLARIFY, str(state))
    check("wizard xabari yuborildi", len(msg.replies) == 1)
    reply = msg.replies[0] if msg.replies else {}
    check("savol matni bor", SPEC_CLARIFY_UZ in reply.get("text", ""),
          reply.get("text", "")[:80])
    cbs = [d for _t, d in kb_buttons(reply.get("reply_markup"))]
    check("5 ta aip_fmt tugma chiqdi", cbs == [c for _t, c in SPEC_BUTTONS_UZ], str(cbs))
    check("mavzu user_data'da saqlandi", ctx.user_data.get("aip_topic") == "sport")
    check("origin=magic saqlandi", ctx.user_data.get("aip_origin") == "magic")

    # 5b) Batafsil mavzu → STYLE_SELECT (REGRESSIYA YO'Q).
    ctx2 = FakeContext(lang="uz")
    raw = "Yangi koffemiz 20% chegirma bilan sotilmoqda, dizayner stakanlar"
    msg2 = FakeMessage(text=raw)
    state2 = run(mp.magic_text_received(FakeUpdate(message=msg2), ctx2))
    check("batafsil mavzu → MAGIC_STYLE_SELECT", state2 == mp.MAGIC_STYLE_SELECT,
          str(state2))
    check("xom matn saqlandi", ctx2.user_data.get("magic_raw_text") == raw)
    cbs2 = [d for _t, d in kb_buttons(msg2.replies[0]["reply_markup"])]
    check("5 uslub tugmasi (mp_style:*) chiqdi",
          {c.split(':')[0] for c in cbs2} == {"mp_style"} and len(cbs2) == 5, str(cbs2))

    # 5c) RU batafsil mavzu → STYLE_SELECT (regressiya yo'q).
    ctx_ru = FakeContext(lang="ru")
    msg_ru = FakeMessage(text="Новый кофе со скидкой 20%")
    state_ru = run(mp.magic_text_received(FakeUpdate(message=msg_ru), ctx_ru))
    check("RU batafsil mavzu → MAGIC_STYLE_SELECT",
          state_ru == mp.MAGIC_STYLE_SELECT, str(state_ru))

    # 5d) Qisqa sotuv mavzusi → SALES_INPUT + parametr so'rovi.
    ctx3 = FakeContext(lang="uz")
    msg3 = FakeMessage(text="krossovka sotiladi")
    state3 = run(mp.magic_text_received(FakeUpdate(message=msg3), ctx3))
    check("«krossovka sotiladi» → AI_POST_SALES_INPUT",
          state3 == aip.AI_POST_SALES_INPUT, str(state3))
    check("parametr so'rovi chiqdi", SPEC_SALES_UZ in msg3.replies[0]["text"])

    # 5e) 📰 format tanlandi → uslublar menyusi (magic_raw_text toza).
    ctx4 = FakeContext(lang="uz")
    ctx4.user_data.update({"aip_topic": "sport", "aip_origin": "magic"})
    q_news = FakeQuery("aip_fmt:news")
    state4 = run(aip.ai_post_format_callback(FakeUpdate(query=q_news), ctx4))
    check("📰 → MAGIC_STYLE_SELECT", state4 == mp.MAGIC_STYLE_SELECT, str(state4))
    check("magic_raw_text toza saqlandi",
          ctx4.user_data.get("magic_raw_text") == "sport",
          repr(ctx4.user_data.get("magic_raw_text")))
    check("format hint generatsiyaga tayyor",
          bool(ctx4.user_data.get("aip_format_hint")),
          repr(ctx4.user_data.get("aip_format_hint")))
    menu_cbs = [d for _t, d in kb_buttons(q_news.edits[-1].get("reply_markup"))]
    check("uslublar menyusi chizildi", len(menu_cbs) == 5
          and all(c.startswith("mp_style:") for c in menu_cbs), str(menu_cbs))

    # 5f) Hint generatsiya materialiga ulanadi (display toza qoladi).
    ctx5 = FakeContext(lang="uz")
    ctx5.user_data.update({"magic_raw_text": "sport",
                           "aip_format_hint": "[Format: 📰 test]"})
    q_style = FakeQuery("mp_style:informative")
    captured = {}

    async def fake_gen(raw, style, lang="uz", is_pro=False, timeout=None):
        captured["raw"] = raw
        captured["style"] = style
        return {"post_text": "<b>Test</b> matn #a #b #c", "style": style, "lang": lang}

    with patch("handlers.magic_post.db.run_db", new=_fake_run_db), \
         patch("handlers.magic_post.generate_magic_post", new=fake_gen):
        state5 = run(mp.magic_style_callback(FakeUpdate(query=q_style), ctx5))
    check("hint bilan generatsiya → MAGIC_RESULT", state5 == mp.MAGIC_RESULT,
          str(state5))
    check("materialga hint ulangan",
          captured.get("raw", "").startswith("sport")
          and "[Format: 📰 test]" in captured.get("raw", ""),
          repr(captured.get("raw")))

    # 5g) Sotuv parametrlari keldi → STYLE_SELECT + birlashgan mavzu.
    ctx6 = FakeContext(lang="uz")
    ctx6.user_data.update({"aip_topic": "krossovka", "aip_origin": "magic"})
    msg6 = FakeMessage(text="Erkaklar krossovkasi, 250 000 so'm, bepul yetkazib berish")
    state6 = run(aip.ai_post_sales_input_received(FakeUpdate(message=msg6), ctx6))
    check("parametrlar → MAGIC_STYLE_SELECT", state6 == mp.MAGIC_STYLE_SELECT,
          str(state6))
    combined = ctx6.user_data.get("magic_raw_text", "")
    check("mavzu birlashdi (mavzu + parametrlar)",
          "krossovka" in combined and "250 000" in combined, combined[:80])

    # 5h) ✍️ → CUSTOM_INPUT; aniq matn → STYLE_SELECT (takroriy wizard YO'Q).
    ctx7 = FakeContext(lang="uz")
    ctx7.user_data.update({"aip_topic": "sport", "aip_origin": "magic"})
    q_custom = FakeQuery("aip_fmt:custom")
    state7 = run(aip.ai_post_format_callback(FakeUpdate(query=q_custom), ctx7))
    check("✍️ → AI_POST_CUSTOM_INPUT", state7 == aip.AI_POST_CUSTOM_INPUT, str(state7))
    msg7 = FakeMessage(text="Talabalar uchun ertalabki sportning 5 foydasi")
    state7b = run(aip.ai_post_custom_input_received(FakeUpdate(message=msg7), ctx7))
    check("aniq matn → MAGIC_STYLE_SELECT (wizard takrorlanmaydi)",
          state7b == mp.MAGIC_STYLE_SELECT, str(state7b))
    # Hatto yana "sport" yozilsa ham — cheksiz sikl YO'Q.
    ctx7c = FakeContext(lang="uz")
    ctx7c.user_data.update({"aip_topic": "sport", "aip_origin": "magic"})
    msg7c = FakeMessage(text="sport")
    state7c = run(aip.ai_post_custom_input_received(FakeUpdate(message=msg7c), ctx7c))
    check("takroriy «sport» ham STYLE_SELECT (siklsiz)", state7c == mp.MAGIC_STYLE_SELECT,
          str(state7c))

    # 5i) Stale callback — xavfsiz (crash yo'q, input holatiga).
    ctx8 = FakeContext(lang="uz")
    q_stale = FakeQuery("aip_fmt:news")
    state8 = run(aip.ai_post_format_callback(FakeUpdate(query=q_stale), ctx8))
    check("stale → MAGIC_INPUT (xavfsiz)", state8 == mp.MAGIC_INPUT, str(state8))
    check("stale toast ko'rsatildi",
          any(a[1] for a in q_stale.answers), str(q_stale.answers))

    # 5j) AI Studio'da "sport" → CLARIFY, generatsiya/kvota YO'Q.
    async def _boom(*args, **kwargs):  # pragma: no cover
        raise AssertionError("generatsiya chaqirilmasligi kerak edi!")

    ctx9 = FakeContext(lang="uz")
    msg9 = FakeMessage(text="sport")
    with patch("handlers.ai_assistant.generate_ai_response", new=_boom):
        state9 = run(ai.ai_prompt_received(FakeUpdate(message=msg9), ctx9))
    check("Studio «sport» → AI_POST_CLARIFY (generatsiyasiz)",
          state9 == aip.AI_POST_CLARIFY, str(state9))
    check("wizard savoli chiqdi",
          any(SPEC_CLARIFY_UZ in r["text"] for r in msg9.replies))
    check("Studio bron/qoldiq yaratmadi (studio_post_text yo'q)",
          "studio_post_text" not in ctx9.user_data)
    check("origin=studio saqlandi", ctx9.user_data.get("aip_origin") == "studio")

    # 5k) Studio'da batafsil mavzu → generatsiya yo'li (regressiya yo'q).
    ctx10 = FakeContext(lang="uz")
    msg10 = FakeMessage(text="Talabalar uchun ertalabki sportning beshta foydasi ro'yxati")

    async def _fake_preflight(update, context):
        return True, True, False  # admin — kvotasiz

    async def _fake_gen_studio(prompt, is_pro=False, lang="uz", **kwargs):
        return {"intent": "post",
                "post_text": "<b>Sport</b> foydali. #sport #soglom #kun"}

    with patch("handlers.ai_assistant._studio_ai_preflight", new=_fake_preflight), \
         patch("handlers.ai_assistant.generate_ai_response", new=_fake_gen_studio):
        state10 = run(ai.ai_prompt_received(FakeUpdate(message=msg10), ctx10))
    check("Studio batafsil mavzu → AI_TONE_SELECT", state10 == ai.AI_TONE_SELECT,
          str(state10))

    # 5l) Studio resume: 📰 tanlandi → boyitilgan mavzu generatsiyaga.
    ctx11 = FakeContext(lang="uz")
    ctx11.user_data.update({"aip_topic": "sport", "aip_origin": "studio"})
    q_studio = FakeQuery("aip_fmt:news")
    seen = {}

    async def _fake_helper(update, context, msg, text_input, lang):
        seen["topic"] = text_input
        return ai.AI_TONE_SELECT

    with patch("handlers.ai_assistant._studio_generate_and_preview", new=_fake_helper):
        state11 = run(aip.ai_post_format_callback(FakeUpdate(query=q_studio), ctx11))
    check("Studio 📰 → AI_TONE_SELECT", state11 == ai.AI_TONE_SELECT, str(state11))
    check("generatsiyaga format hint bilan uzatildi",
          seen.get("topic", "").startswith("sport") and "[Format:" in seen.get("topic", ""),
          repr(seen.get("topic")))


# ===========================================================================
# TEST 6 — FLUFF-GUARD (quruq shablonlar promptlarda YO'Q)
# ===========================================================================
def _collect_generation_prompts() -> dict:
    """Barcha generatsiya promptlari: {nom: matn}."""
    prompts = {}
    for style in MAGIC_POST_STYLES:
        for lang in LANGS:
            prompts[f"magic:{style}/{lang}"] = MAGIC_POST_SYSTEMS[style][lang]
    for fmt in ("news", "tips", "short", "sales"):
        for lang in LANGS:
            prompts[f"format:{fmt}/{lang}"] = build_format_system(fmt, lang)
    for lang in LANGS:
        prompts[f"quality:{lang}"] = QUALITY_RULES[lang]
        prompts[f"hint:news/{lang}"] = format_hint_line("news", lang)
        prompts[f"hint:sales/{lang}"] = format_hint_line("sales", lang)
    # AI Studio router promptlari (3 til × FREE/PRO).
    from utils import ai_agent as _agent
    for lang in LANGS:
        for pro in (False, True):
            prompts[f"router:{lang}/{'pro' if pro else 'free'}"] = \
                _agent._get_router_system_instruction(is_pro=pro, lang=lang)
    prompts["pro_hint:uz"] = _agent._PRO_POST_ENHANCEMENT
    prompts["free_hint:uz"] = _agent._FREE_POST_HINT
    # Kontent rejasi CTA'lari.
    from services.ai.planner import PLAN_FORMATS
    for item in PLAN_FORMATS:
        for lang in LANGS:
            cta = (item.cta or {}).get(lang, "")
            prompts[f"plan:{item.key}/{lang}"] = f"{item.key} {cta}"
    # Variant uslublari ko'rsatmalari + mock banklar.
    from services.ai.variants import VARIANT_STYLES
    for style in VARIANT_STYLES:
        for lang in LANGS:
            prompts[f"variant:{style.key}/{lang}"] = style.t_instruction(lang)
    from services.ai import smm_mock as _mock
    for style, langs in _mock.VARIANT_BANK.items():
        for lang in LANGS:
            prompts[f"mock:{style}/{lang}"] = langs[lang].format(topic="Mavzu")
    return prompts


def test_fluff_guard():
    print("\n== TEST 6: Fluff-guard — quruq shablonlar yo'q, sifat bor ==")

    check("qora ro'yxat bo'sh emas", len(FORBIDDEN_FLUFF_PHRASES) >= 8,
          str(len(FORBIDDEN_FLUFF_PHRASES)))
    # Skanner o'zi ishlaydi (ijobiy nazorat).
    check("skanner fluff'ni topadi",
          scan_text_for_fluff("Bizning kanal eng ishonchli manba, kanalga obuna bo'ling")
          != [])
    check("skanner toza matnda jim",
          scan_text_for_fluff("Kuchli hook bilan faktlar ro'yxati") == [])

    prompts = _collect_generation_prompts()
    check("promptlar yig'ildi", len(prompts) > 40, str(len(prompts)))
    dirty = {}
    for name, text in prompts.items():
        hits = scan_text_for_fluff(text)
        if hits:
            dirty[name] = hits
    check("BARCHA generatsiya promptlari fluff'siz", not dirty,
          str(list(dirty)[:5]))

    # Sifat standarti: Hook + HTML + ro'yxatlar + aniq mazmun.
    for lang in LANGS:
        q = QUALITY_RULES[lang]
        low = q.lower()
        has_hook = "hook" in low or "хук" in low
        has_html = "<b>" in q and "<i>" in q
        has_list = "•" in q
        check(f"sifat standarti [{lang}]: Hook + HTML + •",
              has_hook and has_html and has_list)
    for fmt in ("news", "tips", "short", "sales"):
        for lang in LANGS:
            sys_prompt = build_format_system(fmt, lang)
            check(f"format prompt [{fmt}/{lang}] sifat blokini o'z ichiga oladi",
                  QUALITY_RULES[lang] in sys_prompt)
    # Sotuv formati: mahsulotsiz to'qish taqiqi.
    sales_uz = build_format_system("sales", "uz")
    check("sotuv formati uydirishni taqiqlaydi",
          "O'YLAB TOPILMAYDI" in sales_uz or "o'ylab topilmaydi" in sales_uz.lower())
    news_uz = build_format_system("news", "uz")
    check("yangilik formati sotuv ohangini taqiqlaydi",
          "TAQIQLANADI" in news_uz)


# ===========================================================================
# TEST 7 — FSM XAVFSIZLIK + PHASE A-E REGRESSIYA
# ===========================================================================
def test_fsm_safety_and_phase_regression():
    print("\n== TEST 7: FSM xavfsizlik + Phase A-E filtrlari joyida ==")

    # 7a) Yangi holatlar noyob.
    from handlers import magic_post as _mp, ai_assistant as _ai
    from handlers import image_post as _ip, voice_post as _vp
    from handlers import manual_post as _mnp, autopilot as _ap
    from handlers import sources as _src, team as _team
    known = {
        _mp.MAGIC_INPUT, _mp.MAGIC_STYLE_SELECT, _mp.MAGIC_RESULT, _mp.MAGIC_SEND_CHOOSE,
        _ai.AI_INPUT, _ai.AI_CONFIRM, _ai.AI_GET_TIME, _ai.AI_MENU_STATE,
        _ai.AI_PROMPT_INPUT, _ai.AI_TONE_SELECT, _ai.AI_AUDIT_INPUT,
        _ai.AI_PHOTO_INPUT, _ai.AI_PHOTO_RESULT, _ai.AI_PHOTO_EDIT_INPUT,
        _ip.IMAGE_POST_INPUT, _ip.IMAGE_STYLE_SELECT, _ip.IMAGE_POST_RESULT,
        _ip.IMAGE_SEND_CHOOSE, _ip.IMAGE_SCHEDULE_INPUT, _ip.IMAGE_TOPIC_INPUT,
        _vp.VOICE_AWAIT, _vp.VOICE_STYLE_SELECT, _vp.VOICE_RESULT, _vp.VOICE_SEND_CHOOSE,
        _mnp.MANUAL_AWAIT_CONTENT, _mnp.MANUAL_PREVIEW, _mnp.MANUAL_CHANNEL_SELECT,
        _mnp.MANUAL_TIME_INPUT, _mnp.MANUAL_EDIT_INPUT, _mnp.MANUAL_REACTION_CUSTOM,
        _ap.AUTOPILOT_TOPIC, _ap.AUTOPILOT_VIEW,
        _src.SOURCES_MENU if hasattr(_src, "SOURCES_MENU") else 530,
    }
    new_states = {aip.AI_POST_CLARIFY, aip.AI_POST_SALES_INPUT, aip.AI_POST_CUSTOM_INPUT}
    check("yangi holatlar (434/435/436)", new_states == {434, 435, 436}, str(new_states))
    check("yangi holatlar boshqa oqimlar bilan to'qnashmaydi",
          not (new_states & known), str(new_states & known))

    # 7b) Callback patternlar ro'yxatda (stale qo'riqchisi bilan).
    import handlers as _handlers_pkg
    import inspect as _inspect
    src = _inspect.getsource(_handlers_pkg)
    check("aip_fmt callback ro'yxatda", "aip_fmt:" in src)
    check("aip_back callback ro'yxatda", "aip_back" in src)
    check("aip stale qo'riqchi ro'yxatda", "^aip_" in src)
    check("AI_POST_CLARIFY holati ro'yxatda", "AI_POST_CLARIFY" in src)

    # 7c) Phase A — production safety (P0-A/B/C) buzilmagan.
    from services.ai.providers import mock_is_allowed, get_environment  # noqa
    from services.ai.validator import AIOutputValidator  # noqa
    from services.ai.prompt_guard import sanitize_output  # noqa
    from services.ai.orchestrator import AIOrchestrator  # noqa
    check("Phase A: mock siyosati joyida", callable(mock_is_allowed))
    check("Phase A: validator joyida",
          hasattr(AIOutputValidator, "validate") and hasattr(AIOutputValidator, "get_retry_prompt_addon"))
    check("Phase A: prompt-guard joyida", callable(sanitize_output))

    # 7d) Phase B — Channel Intelligence (DNA) ulanishi buzilmagan.
    from services.channels.dna import attach_dna_to_context  # noqa
    check("Phase B: DNA ulanishi joyida", callable(attach_dna_to_context))

    # 7e) Phase C — avtopilot + shablonlar + dublikat detektori.
    from services.autopilot.planner import create_autopilot_plan  # noqa
    from services.channels.duplicate_detector import (  # noqa
        DUPLICATE_THRESHOLD, check_duplicate,
    )
    from services.templates.service import (  # noqa
        TEMPLATE_VARIABLES, render_template,
    )
    check("Phase C: avtopilot joyida", callable(create_autopilot_plan))
    check("Phase C: dublikat detektori joyida (0.85)",
          callable(check_duplicate) and DUPLICATE_THRESHOLD == 0.85)
    check("Phase C: shablonlar servisi joyida (7 o'zgaruvchi)",
          callable(render_template) and len(TEMPLATE_VARIABLES) == 7,
          str(TEMPLATE_VARIABLES))

    # 7f) Phase D — kontent manbalari (URL/RSS guard'lar).
    from services.sources.url_extractor import UrlPostService, validate_public_url  # noqa
    from services.sources.rss_service import RssService, parse_feed  # noqa
    check("Phase D: URL SSRF guard joyida", callable(validate_public_url))
    check("Phase D: URL post servisi joyida", UrlPostService is not None)
    check("Phase D: RSS parser joyida",
          callable(parse_feed) and RssService is not None)

    # 7g) Phase E — team rollari + approval.
    from services.channels.team import ApprovalWorkflow, ChannelRole, can_role  # noqa
    from services.channels.advisor import compute_weekly_insights  # noqa
    check("Phase E: team rollari joyida",
          callable(can_role) and hasattr(ChannelRole, "OWNER"))
    check("Phase E: approval oqimi joyida", ApprovalWorkflow is not None)
    check("Phase E: audience insights joyida", callable(compute_weekly_insights))
    check("Phase E: team handleri import qilindi", _team is not None)

    # 7h) Mavjud oqim funksiyalari o'chmadi (import sirtqi).
    check("magic oqimi funksiyalari joyida",
          callable(mp.magic_text_received) and callable(mp.magic_style_callback))
    check("studio oqimi funksiyalari joyida",
          callable(ai.ai_prompt_received) and callable(ai._studio_generate_and_preview))
    check("stale handlerlar joyida",
          callable(aip.ai_post_stale_callback) and callable(mp.magic_stale_callback))


# ===========================================================================
# MAIN
# ===========================================================================
def main():
    print("=" * 62)
    print(" 🧭 3-QADAM — ANIQLASHTIRISH, FORMAT VA SIFAT TESTI")
    print("=" * 62)
    test_clarification_trigger()
    test_format_detection()
    test_sales_params_flow()
    test_wizard_ui()
    test_handler_integration()
    test_fluff_guard()
    test_fsm_safety_and_phase_regression()

    print("\n" + "=" * 62)
    print(f" JAMI: o'tdi={passed}, xato={failures}")
    if failures:
        print(" [FAIL] AYRIM TEKSHIRUVLAR YIQILDI ^^^")
        return 1
    print(" BARCHA ANIQLASHTIRISH TESTLARI 100% YASHIL ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
