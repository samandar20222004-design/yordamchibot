#!/usr/bin/env python3
"""📊 POST SCORE & IMPROVER — KILLER FEATURE #4 OQIM TESTI (deterministik).

Qamrov (topshiriq talablari bilan birma-bir):

  TEST 1:  BAHOLASH (SCORE) — matn yuborilganda 6 mezon (headline,
           readability, cta, engagement, sales_power, structure) 1–10 ball
           bilan hisoblanadi, 100 ballik umumiy natija mezonlar o'rtachasiga
           teng bo'ladi va tavsiya ko'rsatiladi; AI JSON'i buzilgan/markdown
           bo'lsa ham xavfsiz parser ishlaydi. Baholash BEPUL — kredit ham,
           kunlik kvota ham yechilmaydi. AI butunlay ishlamasa lokal
           deterministik zaxira ishlaydi. Magic/Voice/Image natijalaridagi
           «📊 Baholash» tugmasi postni qayta yozdirmasdan baholaydi.
  TEST 2:  «✨ 95/100 ga yaxshilash» — AI takomillashtirilgan matn qaytaradi
           va AYNAN 1 ta AI krediti atomik yechiladi
           (``db.use_user_credit`` → CreditsService); AI xatosida kredit
           qaytariladi (refund); kredit yetmasa yaxshilash boshlanmaydi.
           Kanalga yuborish va rejalashtirish (scheduler) tugmalari ham
           tekshiriladi.
  TEST 3:  NOTO'G'RI / BO'SH MATN — xavfsiz ogohlantirish beriladi, AI
           chaqirilmaydi, kredit/kvota TIYILMAYDI (bo'sh matn, juda qisqa
           matn, faqat tinish belgilari, matnsiz media).
  TEST 4:  i18n PARITET — UZ/RU/EN 100% (kalitlar, {placeholder}lar, bo'sh
           qiymatlar) + mezon nomlari va tugmalar uchala tilda to'liq.
  TEST 5:  REGRESSIYA HIMOYASI — Magic (430-433), Voice (440-442), Image
           (520-524) holatlari o'zgarmagan, yangi holatlar (460-462) bilan
           to'qnashmaydi, eski natija klaviaturalari buzilmagan va
           callback_data 64 bayt chegarasida.

Ishga tushirish:
    bash tests/run_tests.sh                  # yoki
    python3 tests/post_score_flow_test.py
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
os.environ.setdefault("BOT_TOKEN", "123456:POST_SCORE_FLOW_TOKEN")
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
    """Xabar: reply_text (status) va edit_text (statusni yangilash) bilan."""

    def __init__(self, text=None, caption=None):
        self.text = text
        self.caption = caption
        self.chat = SimpleNamespace(id=555000)
        self.replies = []
        self.edits = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kwargs):
        self.replies.append({"text": text, "reply_markup": reply_markup,
                             "parse_mode": parse_mode})
        return self

    async def edit_text(self, text, reply_markup=None, parse_mode=None, **kwargs):
        self.edits.append({"text": text, "reply_markup": reply_markup,
                           "parse_mode": parse_mode})
        return self

    #: Eng oxirgi ko'rsatilgan matn (status edit yoki yangi xabar).
    @property
    def last_text(self) -> str:
        if self.edits:
            return self.edits[-1]["text"]
        if self.replies:
            return self.replies[-1]["text"]
        return ""

    @property
    def last_markup(self):
        if self.edits:
            return self.edits[-1]["reply_markup"]
        if self.replies:
            return self.replies[-1]["reply_markup"]
        return None


class FakeQuery:
    def __init__(self, data, user_id=777000, message=None):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = message or FakeMessage()
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
        self.effective_user = SimpleNamespace(
            id=(query.from_user.id if query else user_id)
        )


class FakeContext:
    def __init__(self, lang="uz", bot=None):
        self.user_data = {"lang": lang}
        self.bot = bot or FakeBot()


def kb_buttons(markup):
    """InlineKeyboardMarkup → [(text, callback_data), ...]."""
    if markup is None:
        return []
    rows = (getattr(markup, "inline_keyboard", None)
            or getattr(markup, "keyboard", []) or [])
    out = []
    for row in rows:
        for btn in row:
            out.append((btn.text, getattr(btn, "callback_data", None)))
    return out


def kb_texts(markup):
    return [text for text, _data in kb_buttons(markup)]


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# MODULLAR (env sozlangandan KEYIN import qilinadi)
# ---------------------------------------------------------------------------
from handlers import magic_post as mp                      # noqa: E402
from handlers import post_score as ps                       # noqa: E402
from handlers import voice_post as vh                       # noqa: E402
from handlers import image_post as ip                       # noqa: E402
from handlers.ai_assistant import AI_GET_TIME               # noqa: E402
from keyboards.callback_data import (                       # noqa: E402
    CALLBACK_DATA_MAX_BYTES, CB_POST_SCORE_EVAL,
    callback_byte_len, is_callback_safe,
)
from keyboards.default import (                             # noqa: E402
    BTN_MAGIC_POST, BTN_POST_SCORE, BTN_POST_SCORE_EN, BTN_POST_SCORE_RU,
    MENU_TEXTS, exact, get_main_keyboard,
)
from locales.translations import normalize_lang             # noqa: E402
from translations import (                                  # noqa: E402
    POST_SCORE_CRITERIA_KEYS, POST_SCORE_I18N, post_score_band,
    post_score_criterion_label, post_score_parity_report, post_score_t,
)
from utils.helpers import safe_html                         # noqa: E402
from utils.post_scorer import (                             # noqa: E402
    POST_SCORE_CRITERIA, TARGET_SCORE, normalize_post_score,
    overall_from_scores, parse_post_score_json, score_bar,
    score_post, score_post_locally, validate_post_text,
)

LANGS = ("uz", "ru", "en")

SAMPLE_POST = (
    "🔥 <b>Yangi kofe — 20% chegirma!</b>\n\n"
    "☕️ Yangi qovurilgan arabika don kofe endi 20% arzon narxda.\n"
    "• Yetkazib berish Toshkent bo'yicha bepul\n"
    "• Kafolat: yoqmasa — pulingiz qaytariladi\n\n"
    "👉 Hoziroq buyurtma uchun yozing!\n\n"
    "#kofe #chegirma #aksiya"
)

#: AI ballash javobi (markdown to'siq + satr ko'rinishidagi ballar bilan).
AI_SCORE_JSON = """```json
{"headline": "9/10", "readability": 8, "cta": 7, "engagement": 6,
 "sales_power": 8, "structure": 9, "overall_score": 78,
 "recommendation": "Oxirgi qatorga aniq savol qo'shing."}
```"""

#: AI takomillashtirilgan post javobi.
AI_IMPROVED_JSON = (
    '{"post_text": "🔥 <b>Yangi kofe — 20% chegirma!</b>\\n\\n'
    "☕️ Yangi qovurilgan arabika endi 20% arzon.\\n"
    "• Yetkazib berish bepul\\n• Kafolat: yoqmasa — pul qaytariladi\\n\\n"
    "👉 Hoziroq buyurtma uchun yozing!\\n\\n"
    '#kofe #chegirma #aksiya", "changes": ["sarlavha", "CTA"]}'
)


# ---------------------------------------------------------------------------
# DB MOCK — handlers.post_score.db.run_db ni almashtiradi.
# Kredit/kvota chaqiruvlari SANALADI (resurs siyosati testi uchun).
# ---------------------------------------------------------------------------
FAKE_CHANNELS = [("-100111001", "Kanal A"), ("-100222002", "Kanal B")]


def make_db(credit_ok=True, channels=None):
    """DB mock quruvchi: chaqiruvlar jurnalini ham qaytaradi."""
    calls = []

    async def fake_run_db(func, *args, **kwargs):
        name = getattr(func, "__name__", str(func))
        calls.append(name)
        if name == "is_premium":
            return False
        if name == "check_ai_limit":
            return (True, 0, 30)
        if name == "use_user_credit":
            return credit_ok
        if name == "get_user_channels":
            return list(FAKE_CHANNELS if channels is None else channels)
        if name in ("add_user_credit", "increment_ai_usage", "refund_ai_usage"):
            return True
        return None

    fake_run_db.calls = calls
    return fake_run_db


def db_patch(credit_ok=True, channels=None):
    fake = make_db(credit_ok=credit_ok, channels=channels)
    return patch("handlers.post_score.db.run_db", new=fake), fake


def ai_patch(payload, calls=None):
    """``utils.post_scorer.generate_ai_response`` o'rniga soxta AI javobi."""
    async def fake_ai(prompt, system_instruction=None, timeout=None,
                      tone=None, is_pro=False, lang="uz"):
        if calls is not None:
            calls.append({"prompt": prompt, "system": system_instruction,
                          "lang": lang, "timeout": timeout, "is_pro": is_pro})
        return payload if not callable(payload) else payload(prompt, system_instruction)

    return patch("utils.post_scorer.generate_ai_response", new=fake_ai)


# ============================================================================
# TEST 1 — BAHOLASH: 6 mezon + umumiy ball + tavsiya (BEPUL)
# ============================================================================
def test_main_menu_entry():
    print("\n== TEST 1a: asosiy menyu «📊 Post Score» + entry ==")

    check("BTN_POST_SCORE = «📊 Post Score»", BTN_POST_SCORE == "📊 Post Score")
    check("MENU_TEXTS'da 'post_score' bor", "post_score" in MENU_TEXTS)
    for lang, label in (("uz", BTN_POST_SCORE), ("ru", BTN_POST_SCORE_RU),
                        ("en", BTN_POST_SCORE_EN)):
        check(f"exact() filtri «📊 Post Score»ni taniydi ({lang})",
              bool(re.fullmatch(exact(BTN_POST_SCORE, BTN_POST_SCORE_RU,
                                      BTN_POST_SCORE_EN).pattern, label)))

    # KLASSIK (6-tugma standarti): asosiy menyu aynan 6 tugma; «📊 Post
    # Score» va «✨ Magic Post» menyu'dan chiqdi (oqimlari yashaydi —
    # routing filtrlari + AI Yordamchi / to'g'ridan-to'g'ri kirishlar).
    kb_ctx = get_main_keyboard(False, lang="uz", context=object())
    texts_ctx = [btn.text for row in kb_ctx.keyboard for btn in row]
    check("production menyu: klassik — aynan 6 tugma", len(texts_ctx) == 6, str(texts_ctx))
    check("production menyuda Post Score YO'Q (UX V2)",
          BTN_POST_SCORE not in texts_ctx, str(texts_ctx))
    check("production menyuda Magic Post YO'Q (UX V2)",
          BTN_MAGIC_POST not in texts_ctx, str(texts_ctx))

    kb_legacy = get_main_keyboard(False, lang="uz")
    legacy_rows = [[btn.text for btn in row] for row in kb_legacy.keyboard]
    check("context'siz klaviatura: klassik — 3 qator (6 tugma)",
          len(legacy_rows) == 3, str(legacy_rows))
    check("context'siz klaviaturada Post Score YO'Q",
          BTN_POST_SCORE not in [t for row in legacy_rows for t in row])

    # Entry: yo'riqnoma + matn kutish holati.
    ctx = FakeContext(lang="uz")
    msg = FakeMessage()
    state = run(ps.post_score_entry(FakeUpdate(message=msg), ctx))
    check("entry POST_SCORE_INPUT qaytaradi", state == ps.POST_SCORE_INPUT)
    check("yo'riqnoma 6 mezonni sanaydi",
          len(msg.replies) == 1 and "🎯" in msg.replies[0]["text"]
          and "💰" in msg.replies[0]["text"]
          and "🧩" in msg.replies[0]["text"])
    check("yo'riqnoma baholash BEPUL ekanini aytadi",
          "bepul" in msg.replies[0]["text"].lower())
    check("yo'riqnoma kredit siyosatini tushuntiradi",
          "1 kredit" in msg.replies[0]["text"].lower())


def test_score_text_flow():
    print("\n== TEST 1b: matn → 6 mezon ballari + umumiy natija + tavsiya ==")

    ctx = FakeContext(lang="uz")
    msg = FakeMessage(text=SAMPLE_POST)
    ai_calls = []

    with ai_patch(AI_SCORE_JSON, ai_calls), db_patch()[0]:
        state = run(ps.post_score_text_received(FakeUpdate(message=msg), ctx))

    check("natijadan keyin POST_SCORE_RESULT", state == ps.POST_SCORE_RESULT)
    out = msg.last_text
    # Mezon ballari va vizual shkala.
    for criterion, expected in (("headline", 9), ("readability", 8), ("cta", 7),
                                ("engagement", 6), ("sales_power", 8),
                                ("structure", 9)):
        label = post_score_criterion_label(criterion, "uz")
        check(f"natijada {criterion} = {expected}/10 ko'rinadi",
              f"{label}" in out and f"<b>{expected}/10</b>" in out, out[:160])
    check("vizual shkala (▰/▱) chizilgan", "▰" in out and "▱" in out)
    check("shkala to'g'ri nisbatda", score_bar(9) in out and score_bar(6) in out)

    # Umumiy ball = mezonlar o'rtachasi × 10 (AI bergan 78 EMAS — izchillik).
    expected_overall = overall_from_scores(
        {"headline": 9, "readability": 8, "cta": 7, "engagement": 6,
         "sales_power": 8, "structure": 9}
    )
    check(f"umumiy ball o'rtachaga teng ({expected_overall}/100)",
          f"{expected_overall}/100" in out, out[:200])
    check("daraja (band) matni ko'rsatilgan",
          post_score_band(expected_overall, "uz") in out)
    check("AI tavsiyasi ko'rsatilgan",
          "Oxirgi qatorga aniq savol qo'shing." in out)

    # Saqlangan sessiya va amallar tugmalari.
    check("ball sessiyaga saqlandi", ctx.user_data.get("ps_score", {}).get("overall")
          == expected_overall)
    check("baholanayotgan matn saqlandi", ctx.user_data.get("ps_text") == SAMPLE_POST)
    btns = kb_buttons(msg.last_markup)
    check("[✨ Yaxshilash] tugmasi bor",
          ("✨ Yaxshilash", ps.PS_IMPROVE) in btns, str(btns))
    check("[📢 Kanalga yuborish] tugmasi bor",
          ("📢 Kanalga yuborish", ps.PS_SEND) in btns, str(btns))
    check("[📅 Rejalashtirish] tugmasi bor",
          ("📅 Rejalashtirish", ps.PS_SCHED) in btns, str(btns))

    # AI so'rovi to'g'ri tizim prompti + til bilan yuborilgan.
    check("AI chaqirildi (sistema + user prompt)", len(ai_calls) == 1)
    system = ai_calls[0]["system"]
    for marker in ('"headline"', '"readability"', '"cta"', '"engagement"',
                   '"sales_power"', '"structure"', '"overall_score"',
                   '"recommendation"'):
        check(f"tizim promptida {marker} maydoni talab qilinadi", marker in system)
    check("tizim prompti 1-10 shkalani belgilaydi", "1-10" in system or "1 dan 10" in system)
    check("user promptda post matni bor", "Yangi kofe" in ai_calls[0]["prompt"])
    check("baholash QAT'IY timeout bilan (25s dan tez)", ai_calls[0]["timeout"] is not None
          and ai_calls[0]["timeout"] <= 25)
    # Baholash — BEPUL operatsiya: kredit ham, kvota ham yechilmaydi.
    check("baholashda AI til bloki uzatildi", ai_calls[0]["lang"] == "uz")
    check("baholashda is_pro=False (bepul rejim)", ai_calls[0]["is_pro"] is False)


def test_score_is_free():
    print("\n== TEST 1c: baholash BEPUL — kredit/kvota sarflanmaydi ==")

    ctx = FakeContext(lang="ru")
    msg = FakeMessage(text=SAMPLE_POST)
    patcher, fake_db = db_patch()
    with ai_patch(AI_SCORE_JSON), patcher:
        run(ps.post_score_text_received(FakeUpdate(message=msg), ctx))
    used = [c for c in fake_db.calls if c in (
        "use_user_credit", "check_ai_limit", "increment_ai_usage", "add_user_credit")]
    check("kredit/kvota funksiyalari CHAQIRILMADI", used == [], str(fake_db.calls))
    check("natija rus tilida ko'rsatilgan", "Результат Post Score" in msg.last_text)

    # Rate-limit himoyasi ham mavjud (AI provayderini flooddan saqlaydi).
    src = (ROOT / "handlers" / "post_score.py").read_text(encoding="utf-8")
    check("baholashda rate-limit qo'llanadi", "check_ai_rate_limit" in src)
    score_body = src.split("async def post_score_text_received", 1)[1].split("\nasync def ", 1)[0]
    # PHASE 2 / 1-qadam: «95/100 ga yaxshilash» endi kvota+kreditni BITTA
    # atomik tranzaksiyada bron qiladi (services.ai_quota.reserve_for_flow →
    # database.reserve_ai_request). Shu sababli handler'da bevosita
    # use_user_credit chaqiruvi YO'Q; bron AYNAN 1 MARTA qilinadi. Eski
    # (legacy) zanjir esa services/ai_quota.py ichida backward compatibility
    # uchun saqlangan — u ham aynan bitta chaqiruvdan iborat.
    quota_src = (ROOT / "services" / "ai_quota.py").read_text(encoding="utf-8")
    check("baholash (score) yo'lida kredit umuman yechilmaydi",
          "use_user_credit" not in score_body
          and "reserve_ai_quota" not in score_body
          and src.count("reserve_for_flow(\n") == 1
          and quota_src.count("db_module.use_user_credit") == 1,
          f"reserve_for_flow={src.count('reserve_for_flow(')}, "
          f"legacy_use_user_credit={quota_src.count('db_module.use_user_credit')}")


def test_local_fallback_when_ai_down():
    print("\n== TEST 1d: AI ishlamasa — lokal deterministik zaxira ==")

    ctx = FakeContext(lang="uz")
    msg = FakeMessage(text=SAMPLE_POST)
    with ai_patch({"error": "barcha provayderlar ishlamadi", "ai_unavailable": True}), \
            db_patch()[0]:
        state = run(ps.post_score_text_received(FakeUpdate(message=msg), ctx))

    check("AI xatosida ham natija ko'rsatiladi", state == ps.POST_SCORE_RESULT)
    payload = ctx.user_data.get("ps_score") or {}
    check("lokal baholash zaxirasi ishladi", payload.get("fallback") is True,
          str(payload))
    check("6 mezon to'liq (1..10)", set(payload.get("scores", {})) == set(POST_SCORE_CRITERIA)
          and all(1 <= v <= 10 for v in payload["scores"].values()))
    local_advice = safe_html(ps.post_score_advice(payload.get("weakest"), "uz"))
    check("lokal tavsiya o'rin egallagan (bo'sh emas)",
          len(payload.get("recommendation") or "") > 0 or local_advice in msg.last_text,
          msg.last_text[-160:])
    check("foydalanuvchiga zaxira haqida xabar beriladi",
          "lokal" in msg.last_text.lower())

    # To'g'ridan-to'g'ri servis ham xato bermaydi.
    result = run(score_post(SAMPLE_POST, lang="uz"))
    check("score_post() AI'siz ham dict qaytaradi", isinstance(result, dict)
          and result.get("overall", 0) > 0)


def test_eval_buttons_in_all_flows():
    print("\n== TEST 1e: Magic/Voice/Image natijalarida «📊 Baholash» ==")

    expected = [("📊 Baholash", f"{CB_POST_SCORE_EVAL}magic")]
    check("Magic natija klaviaturasida «📊 Baholash»",
          expected[0] in kb_buttons(mp._magic_action_keyboard("uz")),
          str(kb_buttons(mp._magic_action_keyboard("uz"))))
    check("Magic klaviaturasi asosiy amallarini saqlagan (2-BOSQICH ixcham layout)",
          {("📢 Kanalga yuborish", "mp_send"), ("📅 Rejalashtirish", "mp_sched"),
           ("✏️ Qayta yozish", "mp_restyle"), ("◀️ Orqaga", "mp_back")} <=
          set(kb_buttons(mp._magic_action_keyboard("uz"))))

    voice_btns = kb_buttons(vh._voice_action_keyboard("uz"))
    check("Voice natija klaviaturasida «📊 Baholash» (ps_eval:voice)",
          ("📊 Baholash", f"{CB_POST_SCORE_EVAL}voice") in voice_btns, str(voice_btns))
    check("Voice klaviaturasi eski tugmalarini saqlagan",
          {("📢 Kanalga yuborish", "vp_send"), ("📅 Rejalashtirish", "vp_sched"),
           ("🔄 Boshqa uslub", "vp_restyle")} <= set(voice_btns))

    image_btns = kb_buttons(ip.image_action_keyboard("uz"))
    check("Image natija klaviaturasida «📊 Baholash» (ps_eval:image)",
          ("📊 Baholash", f"{CB_POST_SCORE_EVAL}image") in image_btns, str(image_btns))
    check("Image klaviaturasi eski tugmalarini saqlagan",
          {("image_send", "image_send"), ("image_schedule", "image_schedule"),
           ("image_restyle", "image_restyle")} <=
          {(d, d) for _t, d in image_btns}, str(image_btns))

    for lang in LANGS:
        check(f"«📊 Baholash» {lang} tiliga tarjima qilingan",
              ps.build_eval_button("magic", lang).text
              == post_score_t("ps_btn_eval", lang))
        check(f"ps_eval callback 64 bayt ichida ({lang})",
              is_callback_safe(ps.build_eval_button("magic", lang).callback_data))

    # --- eval callback: Magic natijasidan baholash (matn qayta so'ralmaydi) ---
    ctx = FakeContext(lang="uz")
    ctx.user_data["magic_post_text"] = SAMPLE_POST
    ctx.user_data["magic_style"] = "sales"
    query = FakeQuery(f"{CB_POST_SCORE_EVAL}magic")

    with ai_patch(AI_SCORE_JSON), db_patch()[0]:
        state = run(ps.post_score_eval_callback(FakeUpdate(query=query), ctx))

    check("eval: Magic natija holati saqlanadi (MAGIC_RESULT)", state == mp.MAGIC_RESULT)
    check("eval: post qayta yozilmasdan baholandi",
          ctx.user_data.get("ps_text") == SAMPLE_POST)
    check("eval: baholash ekrani yuborildi",
          any("Post Score natijasi" in r["text"] for r in query.message.replies),
          str(query.message.replies)[:200])
    score_btns = kb_buttons(query.message.last_markup)
    check("eval: natija ostida 3 amal tugmasi bor",
          {ps.PS_IMPROVE, ps.PS_SEND, ps.PS_SCHED} <= {d for _t, d in score_btns},
          str(score_btns))

    # Magic posti yo'q bo'lsa — xavfsiz "sessiya eskirgan" toast.
    query2 = FakeQuery(f"{CB_POST_SCORE_EVAL}magic")
    run(ps.post_score_eval_callback(FakeUpdate(query=query2), FakeContext(lang="uz")))
    check("eval: matn yo'q bo'lsa xavfsiz toast",
          any(text for text, _alert in query2.answers), str(query2.answers))


# ============================================================================
# TEST 2 — «✨ 95/100 GA YAXSHILASH» + 1 KREDIT (ATOMIK)
# ============================================================================
def _improve_ctx(user_id=880001, lang="uz"):
    ctx = FakeContext(lang=lang)
    ctx.user_data.update({
        "ps_text": SAMPLE_POST,
        "ps_post": "",
        "ps_improved": False,
        "ps_score": score_post_locally(SAMPLE_POST, lang),
    })
    return ctx


def test_improve_charges_exactly_one_credit():
    print("\n== TEST 2a: «95/100 ga yaxshilash» — AI matni + AYNAN 1 kredit ==")

    ctx = _improve_ctx(user_id=880101)
    query = FakeQuery(ps.PS_IMPROVE, user_id=880101)
    patcher, fake_db = db_patch()
    ai_calls = []

    with ai_patch(AI_IMPROVED_JSON, ai_calls), patcher:
        state = run(ps.post_score_improve_callback(FakeUpdate(query=query), ctx))

    check("yaxshilashdan keyin holat saqlanadi (POST_SCORE_RESULT)",
          state == ps.POST_SCORE_RESULT)
    credits = [c for c in fake_db.calls if c == "use_user_credit"]
    check("AYNAN 1 marta kredit yechildi (use_user_credit)", len(credits) == 1,
          str(fake_db.calls))
    check("kredit yechishdan oldin kunlik kvota tekshirildi",
          "check_ai_limit" in fake_db.calls, str(fake_db.calls))
    check("refund CHAQIRILMADI (muvaffaqiyatli oqim)",
          "add_user_credit" not in fake_db.calls, str(fake_db.calls))

    improved = ctx.user_data.get("ps_post") or ""
    check("AI takomillashtirilgan matn qaytardi", "Yangi kofe" in improved
          and improved != SAMPLE_POST)
    check("matn xavfsiz HTML bilan saqlandi (<b> saqlangan)",
          "<b>" in improved and "<script>" not in improved)
    check("hashtaglar kafolati (3-5 ta)", 3 <= len(re.findall(r"#\w+", improved)) <= 5,
          str(re.findall(r"#\w+", improved)))
    check("ps_improved = True", ctx.user_data.get("ps_improved") is True)
    check("yangi ball sessiyada", (ctx.user_data.get("ps_score") or {}).get("overall", 0) > 0)

    out = query.edits[-1]["text"]
    check("yaxshilangan matn foydalanuvchiga ko'rsatildi", "Yangi kofe" in out)
    check("yangi ball sarlavhasi ko'rsatildi",
          "yaxshilandi" in out.lower() and "/100" in out)
    check("natija ostida amallar tugmalari bor",
          {ps.PS_IMPROVE, ps.PS_SEND, ps.PS_SCHED} <=
          {d for _t, d in kb_buttons(query.edits[-1]["reply_markup"])})

    # AI takomillashtirish prompti: 95+ maqsad + sarlavha/CTA/hashtag qoidalari.
    system = ai_calls[0]["system"]
    check("tizim promptida 95/100 maqsadi bor", "95" in system)
    check("tizim promptida sarlavha qoidasi bor", "<b>" in system)
    check("tizim promptida hashtag qoidasi bor", "3-5" in system)
    check("tizim promptida faktlarni saqlash qoidasi bor",
          "fakt" in system.lower())
    check("yaxshilash promptida post matni bor", "Yangi kofe" in ai_calls[0]["prompt"])
    check("maqsadli ball konstantasi 95", TARGET_SCORE == 95)

    # «✨ Yaxshilash» tugmasi matni (3 til, qisqa variant).
    check("tugma matni uz: «✨ Yaxshilash»",
          post_score_t("ps_btn_improve", "uz") == "✨ Yaxshilash")
    check("tugma matni ru/en ham mavjud",
          "Улучшить" in post_score_t("ps_btn_improve", "ru")
          and "Improve" in post_score_t("ps_btn_improve", "en"))


def test_improve_refunds_on_ai_failure():
    print("\n== TEST 2b: AI xatosi → kredit qaytariladi (refund) ==")

    ctx = _improve_ctx(user_id=880202)
    query = FakeQuery(ps.PS_IMPROVE, user_id=880202)
    patcher, fake_db = db_patch()

    with ai_patch({"error": "timeout", "timeout": True}), patcher:
        run(ps.post_score_improve_callback(FakeUpdate(query=query), ctx))

    check("xatoda kredit yechilgan (1 marta)",
          fake_db.calls.count("use_user_credit") == 1, str(fake_db.calls))
    check("xatoda kredit QAYTARILDI (add_user_credit)",
          fake_db.calls.count("add_user_credit") == 1, str(fake_db.calls))
    check("foydalanuvchiga refund haqida xabar berildi",
          "qaytarildi" in query.edits[-1]["text"].lower(), query.edits[-1]["text"][:120])
    check("ps_post bo'sh qoldi (yaroqsiz matn saqlanmadi)",
          not (ctx.user_data.get("ps_post") or ""))
    check("oqim davom eta oladi (tugmalar qaytarildi)",
          ps.PS_IMPROVE in {d for _t, d in kb_buttons(query.edits[-1]["reply_markup"])})


def test_improve_without_credits():
    print("\n== TEST 2c: kredit yetmasa — yaxshilash boshlanmaydi ==")

    ctx = _improve_ctx(user_id=880303)
    query = FakeQuery(ps.PS_IMPROVE, user_id=880303)
    patcher, fake_db = db_patch(credit_ok=False)
    ai_calls = []

    with ai_patch(AI_IMPROVED_JSON, ai_calls), patcher:
        state = run(ps.post_score_improve_callback(FakeUpdate(query=query), ctx))

    check("AI UMUMAN chaqirilmadi", ai_calls == [], str(len(ai_calls)))
    check("kredit yetmasligi xabari ko'rsatildi",
          "kredit" in query.edits[-1]["text"].lower(), query.edits[-1]["text"][:120])
    check("holat saqlanadi (qayta urinish mumkin)", state == ps.POST_SCORE_RESULT)


def test_send_and_schedule_from_result():
    print("\n== TEST 2d: [📢 Kanalga yuborish] va [📅 Rejalashtirish] ==")

    # --- Bitta kanal → darhol yuborish ---
    deliver_calls = []

    async def fake_deliver(bot, chat_id, post_text):
        deliver_calls.append((chat_id, post_text))
        return True

    ctx = _improve_ctx(user_id=880404)
    ctx.user_data["ps_post"] = "🔥 Tayyor post\n\n#kofe #aksiya"
    query = FakeQuery(ps.PS_SEND, user_id=880404)
    patcher, _db = db_patch(channels=[("-100333", "Mening Kanalim")])

    with patcher, patch("handlers.post_score._magic_deliver_one", new=fake_deliver):
        state = run(ps.post_score_send_callback(FakeUpdate(query=query), ctx))

    check("bitta kanalga darhol yuborildi", deliver_calls
          and deliver_calls[0][0] == "-100333"
          and "Tayyor post" in deliver_calls[0][1], str(deliver_calls)[:160])
    check("yuborilgach sessiya yopildi", state == ps.ConversationHandler.END)
    check("muvaffaqiyat xabari ko'rsatildi",
          any("yuborildi" in e.get("text", "").lower() for e in query.edits),
          str(query.edits[-1:])[:160])

    # --- Ko'p kanal → tanlov menyusi → «hammasi» ---
    ctx2 = _improve_ctx(user_id=880505)
    ctx2.user_data["ps_post"] = "Post"
    query2 = FakeQuery(ps.PS_SEND, user_id=880505)
    deliver_calls.clear()
    patcher2, _db2 = db_patch()
    with patcher2, patch("handlers.post_score._magic_deliver_one", new=fake_deliver):
        state2 = run(ps.post_score_send_callback(FakeUpdate(query=query2), ctx2))
    check("ko'p kanal → POST_SCORE_SEND_CHOOSE", state2 == ps.POST_SCORE_SEND_CHOOSE)
    ch_btns = kb_buttons(query2.edits[-1]["reply_markup"])
    check("kanal tugmalari + «Barcha kanallarga»",
          any(d == ps.PS_SEND_ALL for _t, d in ch_btns)
          and any(d and d.startswith(ps.PS_CHANNEL_PREFIX) for _t, d in ch_btns),
          str(ch_btns))

    query2b = FakeQuery(ps.PS_SEND_ALL, user_id=880505)
    with patcher2, patch("handlers.post_score._magic_deliver_one", new=fake_deliver):
        state2b = run(ps.post_score_channel_picked_callback(
            FakeUpdate(query=query2b), ctx2))
    check("«Barcha kanallarga» — ikkala kanalga yuborildi",
          sorted(c[0] for c in deliver_calls) == ["-100111001", "-100222002"],
          str(deliver_calls))
    check("yuborilgach sessiya yopildi (chall)", state2b == ps.ConversationHandler.END)

    # --- Rejalashtirish: scheduler oqimiga kalitlar bilan uzatish ---
    ctx3 = _improve_ctx(user_id=880606)
    ctx3.user_data["ps_post"] = "🔥 Rejalashtiriladigan post"
    query3 = FakeQuery(ps.PS_SCHED, user_id=880606)
    shown = {}

    async def fake_time_prompt(msg, post_text, file_id, post_type, lang="uz"):
        shown.update({"post": post_text, "file_id": file_id,
                      "post_type": post_type, "lang": lang})

    with patch("handlers.post_score._show_time_prompt", new=fake_time_prompt):
        state3 = run(ps.post_score_schedule_callback(FakeUpdate(query=query3), ctx3))

    check("scheduler holatiga o'tdi (AI_GET_TIME)", state3 == AI_GET_TIME)
    check("post scheduler kalitiga qo'yildi",
          ctx3.user_data.get("ai_generated_post") == "🔥 Rejalashtiriladigan post")
    check("media kalitlari text rejimida",
          ctx3.user_data.get("ai_post_type") == "text"
          and ctx3.user_data.get("ai_file_id") is None)
    check("vaqt tanlash oynasi ko'rsatildi",
          shown.get("post") == ctx3.user_data.get("ai_generated_post")
          and shown.get("lang") == "uz")


# ============================================================================
# TEST 3 — NOTO'G'RI / BO'SH MATN: XAVFSIZ OGOHLANTIRISH
# ============================================================================
def test_invalid_input_warnings():
    print("\n== TEST 3: bo'sh / yaroqsiz matn → xavfsiz ogohlantirish ==")

    # a) Bo'sh matn.
    ctx = FakeContext(lang="uz")
    msg = FakeMessage(text="   ")
    ai_calls = []
    patcher, fake_db = db_patch()
    with ai_patch(AI_SCORE_JSON, ai_calls), patcher:
        state = run(ps.post_score_text_received(FakeUpdate(message=msg), ctx))
    check("bo'sh matnda holat matn kutishda qoladi", state == ps.POST_SCORE_INPUT)
    check("bo'sh matnda AI chaqirilmadi", ai_calls == [])
    check("bo'sh matnda kredit yechilmadi", "use_user_credit" not in fake_db.calls)
    check("bo'sh matn uchun ogohlantirish", "Bo'sh post" in msg.last_text, msg.last_text[:80])

    # b) Matnsiz media (rasm/stiker).
    msg2 = FakeMessage(text=None, caption=None)
    ctx2 = FakeContext(lang="uz")
    with db_patch()[0]:
        state2 = run(ps.post_score_text_received(FakeUpdate(message=msg2), ctx2))
    check("media uchun xavfsiz ogohlantirish", state2 == ps.POST_SCORE_INPUT
          and "faqat" in msg2.replies[-1]["text"].lower(), msg2.replies[-1]["text"][:80])

    # c) Juda qisqa matn.
    msg3 = FakeMessage(text="salom")
    ctx3 = FakeContext(lang="uz")
    ai_calls3 = []
    with ai_patch(AI_SCORE_JSON, ai_calls3), db_patch()[0]:
        state3 = run(ps.post_score_text_received(FakeUpdate(message=msg3), ctx3))
    check("juda qisqa matn baholanmaydi", state3 == ps.POST_SCORE_INPUT)
    check("qisqa matnda AI chaqirilmadi", ai_calls3 == [])
    check("qisqa matn uchun ogohlantirish",
          "juda qisqa" in msg3.last_text.lower(), msg3.last_text[:80])

    # d) Faqat tinish belgilari/HTML (mazmunsiz).
    msg4 = FakeMessage(text="<b></b> !!! ???")
    ctx4 = FakeContext(lang="uz")
    ai_calls4 = []
    with ai_patch(AI_SCORE_JSON, ai_calls4), db_patch()[0]:
        state4 = run(ps.post_score_text_received(FakeUpdate(message=msg4), ctx4))
    check("mazmunsiz matn baholanmaydi", state4 == ps.POST_SCORE_INPUT and ai_calls4 == [])

    # e) Servis darajasidagi validatsiya (handler ham, servis ham himoyalangan).
    check("validate: bo'sh → 'empty'", validate_post_text("")[1] == "empty")
    check("validate: bo'sh joy → 'empty'", validate_post_text("  \n ")[1] == "empty")
    check("validate: tinish belgilari → 'no_content'",
          validate_post_text("!!!")[1] == "no_content")
    check("validate: qisqa matn → 'too_short'",
          validate_post_text("salom")[1] == "too_short")
    check("validate: yaroqli matn → xatosiz",
          validate_post_text(SAMPLE_POST) == (validate_post_text(SAMPLE_POST)[0], ""))

    result = run(score_post(""))
    check("score_post('') → xavfsiz error dict", result.get("error") == "empty")
    result_none = run(score_post(None))
    check("score_post(None) → xavfsiz error dict", result_none.get("error") == "empty")
    improve = run(ps.improve_post_to_95(""))
    check("improve_post_to_95('') → xavfsiz error dict", bool(improve.get("error")))

    # f) Buzilgan JSON — parser hech qachon yiqilmaydi.
    for raw in ("", "salom dunyo", "{", None, 42, "[]", "```\nnot json\n```"):
        parsed = parse_post_score_json(raw)
        check(f"parser xavfsiz: {str(raw)[:18]!r} → dict", isinstance(parsed, dict))


# ============================================================================
# TEST 4 — i18n PARITET (UZ / RU / EN)
# ============================================================================
def test_i18n_parity():
    print("\n== TEST 4: i18n paritet (uz/ru/en) ==")

    report = post_score_parity_report()
    check(f"kalitlar soni > 35 ({report['keys']})", report["keys"] >= 35)
    check("RU'da yetishmayotgan kalit yo'q", report["missing"].get("ru") == [],
          str(report["missing"]))
    check("EN'da yetishmayotgan kalit yo'q", report["missing"].get("en") == [])
    check("ortiqcha kalit yo'q", not report["extra"].get("ru") and not report["extra"].get("en"))
    check("{placeholder}lar uchala tilda bir xil", not report["format_mismatch"],
          str(report["format_mismatch"]))
    check("bo'sh qiymatli kalit yo'q", not report["empty"], str(report["empty"]))
    check("PARITET 100% (in_sync)", report["in_sync"] is True)

    # Handler ishlatgan HAR BIR post_score_t kaliti uchala tilda mavjud.
    src = (ROOT / "handlers" / "post_score.py").read_text(encoding="utf-8")
    used = set(re.findall(r'post_score_t\(\s*"([a-z0-9_]+)"', src))
    check(f"handler {len(used)} ta post_score_t kaliti ishlatgan", len(used) >= 15)
    missing = [f"{lang}:{key}" for key in used for lang in LANGS
               if key not in (POST_SCORE_I18N.get(lang) or {})]
    check("handler kalitlari uchala tilda to'liq", not missing, str(sorted(missing)[:6]))

    # 6 mezon nomi 3 tilda ham mavjud va o'zaro farqli (tarjima qilingan).
    for criterion in POST_SCORE_CRITERIA_KEYS:
        labels = [post_score_criterion_label(criterion, lang) for lang in LANGS]
        check(f"mezon '{criterion}' uchala tilda to'liq", all(labels), str(labels))
        if criterion == "cta":
            # CTA — xalqaro qisqartma: uchala tilda bir xil qoladi.
            check("mezon 'cta' yorlig'i uchala tilda bir xil", len(set(labels)) == 1,
                  str(labels))
        else:
            check(f"mezon '{criterion}' tarjimalari farqli", len(set(labels)) == 3,
                  str(labels))

    # Tavsiyalar (eng kuchsiz mezon uchun) 3 tilda mavjud.
    for criterion in POST_SCORE_CRITERIA_KEYS:
        values = [ps.post_score_advice(criterion, lang) for lang in LANGS]
        check(f"tavsiya '{criterion}' 3 tilda mavjud", all(len(v) > 30 for v in values),
              str(values)[:120])

    # Formatli kalitlar uchala tilda formatlanadi (KeyError yo'q).
    for key in ("ps_overall_line", "ps_recommendation_label", "ps_improved_header",
                "ps_sent_ok", "ps_send_all"):
        for lang in LANGS:
            value = post_score_t(key, lang, overall=70, band="X", text="T",
                                 channels="C", count=2)
            check(f"post_score_t('{key}', {lang}) formatlandi", "{" not in value, value)

    # Topshiriqdagi tugma matnlari (uz) aynan shunday.
    uz = POST_SCORE_I18N["uz"]
    check("«📊 Baholash» (uz)", uz["ps_btn_eval"] == "📊 Baholash")
    check("«✨ Yaxshilash» (uz)", uz["ps_btn_improve"] == "✨ Yaxshilash")
    check("«📢 Kanalga yuborish» (uz)", uz["ps_btn_send"] == "📢 Kanalga yuborish")
    check("«📅 Rejalashtirish» (uz)", uz["ps_btn_schedule"] == "📅 Rejalashtirish")

    # Mezon nomlari topshiriqda ko'rsatilgan tushunchalarni qamraydi.
    for lang, keywords in (
        ("uz", ("Sarlavha", "O'qilishi", "CTA", "Qiziqarlilik", "Sotuv", "Struktura")),
        ("ru", ("Заголовок", "Читаемость", "CTA", "Вовлечённость", "продажи", "Структура")),
        ("en", ("Headline", "Readability", "CTA", "Engagement", "Selling", "Structure")),
    ):
        table = POST_SCORE_I18N[lang]
        joined = " ".join(table[f"ps_label_{c}"] for c in POST_SCORE_CRITERIA_KEYS)
        check(f"mezon nomlari ({lang}) to'liq to'plam", all(k in joined for k in keywords),
              joined)

    for lang in LANGS:
        check(f"normalize_lang({lang}) barqaror", normalize_lang(lang) == lang)


# ============================================================================
# TEST 5 — REGRESSIYA HIMOYASI (Magic / Voice / Image / callback limiti)
# ============================================================================
def test_regression_guard():
    print("\n== TEST 5: regressiya himoyasi ==")

    check("Magic holatlari o'zgarmagan (430-433)",
          (mp.MAGIC_INPUT, mp.MAGIC_STYLE_SELECT, mp.MAGIC_RESULT,
           mp.MAGIC_SEND_CHOOSE) == (430, 431, 432, 433))
    check("Voice holatlari o'zgarmagan (440-442)",
          (vh.VOICE_STYLE_SELECT, vh.VOICE_RESULT, vh.VOICE_SEND_CHOOSE)
          == (440, 441, 442))
    check("Image holatlari o'zgarmagan (520-524)",
          (ip.IMAGE_POST_INPUT, ip.IMAGE_STYLE_SELECT, ip.IMAGE_POST_RESULT,
           ip.IMAGE_SEND_CHOOSE, ip.IMAGE_SCHEDULE_INPUT) == (520, 521, 522, 523, 524))
    check("Post Score holatlari yangi va noyob (460-462)",
          (ps.POST_SCORE_INPUT, ps.POST_SCORE_RESULT, ps.POST_SCORE_SEND_CHOOSE)
          == (460, 461, 462))

    all_states = [mp.MAGIC_INPUT, mp.MAGIC_STYLE_SELECT, mp.MAGIC_RESULT,
                  mp.MAGIC_SEND_CHOOSE, vh.VOICE_STYLE_SELECT, vh.VOICE_RESULT,
                  vh.VOICE_SEND_CHOOSE, ip.IMAGE_POST_INPUT, ip.IMAGE_STYLE_SELECT,
                  ip.IMAGE_POST_RESULT, ip.IMAGE_SEND_CHOOSE, ip.IMAGE_SCHEDULE_INPUT,
                  ps.POST_SCORE_INPUT, ps.POST_SCORE_RESULT, ps.POST_SCORE_SEND_CHOOSE]
    check("FSM holatlari orasida to'qnashuv yo'q",
          len(set(all_states)) == len(all_states), str(sorted(all_states)))

    check("Magic Post i18n pariteti buzilmagan",
          __import__("translations").magic_post_parity_report()["in_sync"] is True)
    check("Voice Post i18n pariteti buzilmagan",
          __import__("translations").voice_post_parity_report()["in_sync"] is True)

    # Magic natija matni/klaviaturasi va voice/image tugmalari joyida.
    check("Magic natija ekrani saqlangan",
          "Magic Post tayyor" in mp._magic_result_text("<b>x</b>", "sales", "uz"))
    check("Magic uslub klaviaturasi 5 uslub + bekor", len(kb_buttons(
        mp._magic_style_keyboard("uz"))) == 6)
    check("Magic send callback'i o'zgarmagan", mp.MP_SEND == "mp_send")

    # Post Score callback'lari kanonik va 64 bayt chegarasida.
    for data in (ps.PS_IMPROVE, ps.PS_SEND, ps.PS_SCHED, ps.PS_NEW, ps.PS_SEND_ALL,
                 ps.PS_EVAL_PREFIX + "magic", ps.PS_CHANNEL_PREFIX + "1"):
        check(f"callback xavfsiz: {data!r}",
              is_callback_safe(data) and callback_byte_len(data) <= CALLBACK_DATA_MAX_BYTES)

    # Router: yangi entry handler va holatlar ro'yxatdan o'tgan.
    src = (ROOT / "handlers" / "__init__.py").read_text(encoding="utf-8")
    for marker in ("post_score_handlers +", "POST_SCORE_INPUT: all_menu_jumps +",
                   "POST_SCORE_RESULT: all_menu_jumps +",
                   "POST_SCORE_SEND_CHOOSE: all_menu_jumps +",
                   "post_score_stale_callback, pattern=r\"^ps_\""):
        check(f"router'da: {marker[:44]!r}", marker in src)

    # Xavfsiz JSON parser: buzilgan javoblar ham o'qiladi.
    parsed = parse_post_score_json("{headline: 8, readability: 7, cta: 5,")
    check("regex zaxira ballarni yig'adi", parsed.get("headline") == 8, str(parsed))
    normalized = normalize_post_score(
        {"headline": "8/10", "readability": 7}, text=SAMPLE_POST)
    check("normalize: yetishmagan mezonlar to'ldiriladi",
          set(normalized["scores"]) == set(POST_SCORE_CRITERIA))
    check("normalize: overall 1..100 oralig'ida",
          1 <= normalized["overall"] <= 100, str(normalized["overall"]))
    check("normalize: bo'sh javob → None (lokal zaxiraga o'tadi)",
          normalize_post_score("umuman json emas") is None)
    check("lokal baholash deterministik",
          score_post_locally(SAMPLE_POST)["overall"]
          == score_post_locally(SAMPLE_POST)["overall"])


# ============================================================================
def main():
    print("=" * 62)
    print(" 📊 POST SCORE & IMPROVER — KILLER FEATURE #4 OQIM TESTI")
    print("=" * 62)
    test_main_menu_entry()
    test_score_text_flow()
    test_score_is_free()
    test_local_fallback_when_ai_down()
    test_eval_buttons_in_all_flows()
    test_improve_charges_exactly_one_credit()
    test_improve_refunds_on_ai_failure()
    test_improve_without_credits()
    test_send_and_schedule_from_result()
    test_invalid_input_warnings()
    test_i18n_parity()
    test_regression_guard()

    print("\n" + "=" * 62)
    print(f" JAMI: o'tdi={passed}, xato={failures}")
    if failures:
        print(" [FAIL] POST SCORE OQIMIDA XATOLIKLAR BOR ^^^")
        return 1
    print(" BARCHA POST SCORE TESTLARI 100% YASHIL ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
