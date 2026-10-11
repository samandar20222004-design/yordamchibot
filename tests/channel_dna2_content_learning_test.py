#!/usr/bin/env python3
"""🧬 STEP 3 — CHANNEL DNA 2.0 & CONTENT LEARNING INTEGRATION TEST.

Qamrov (topshiriq spetsifikatsiyasi bilan birma-bir):

  TEST 1:  🧬 DNA 2.0 PROMPT BUILDER — post generatsiya promptiga kanal
           OHANGI (tone), UZUNLIK AFZALLIGI, CTA USLUBI va LUG'AT
           CHEKLOVLARI (vocabulary limits) AVTOMATIK ulanadi; legacy
           kontrakt ("KANAL USLUBI (DNA)" / "СТИЛЬ КАНАЛА (DNA)" /
           "CHANNEL STYLE (DNA)") saqlanadi; kam ma'lumotda (sample < 5)
           BO'SH (soxta uslub yo'q); tone yo'q bo'lsa tone bo'limi
           UYDIRILMAYDI.
  TEST 2:  🛟 GRACEFUL FALLBACK — DNA tahlil qilinmagan kanal uchun
           standart ohang bloki (uz/ru/en): xatosiz, "DNA" so'zsiz,
           soxta metrikasiz.
  TEST 3:  🔌 attach_dna_to_context — DNA 2.0 ulanishi (owner), standart
           ohang fallback (profil yo'q / yupqa profil), IDOR (begona kanal
           O'ZGARMAYDI), skip_dna, kengaytirilgan profil PRIORITETI
           (channel_dna → tone bo'limi), fail-soft (DB xatosi → xato yo'q).
  TEST 4:  🤖 ORKESTRATOR — AIOrchestrator end-to-end: DNA 2.0 bloki
           provayder kontekstida; profilsiz kanalda standart ohang bilan
           generatsiya MUVAFFAQIYATLI davom etadi.
  TEST 5:  📚 CONTENT LEARNING (PURE) — format tasnifi (Q&A, tutorial,
           ijtimoiy isbot ... uz/ru/en), gap deteksiya, insufficient data
           (NO FABRICATION: tavsiyalar bo'sh, real {n}/{min} sonlari).
  TEST 6:  🌍 RENDER + i18n PARITET — hisobot bloklari uchala tilda
           (uz/ru/en) 100% paritet (kalitlar + format argumentlari),
           halol "ma'lumot yo'q" xabarlari.
  TEST 7:  🔐 get_content_learning_for_user — IDOR (faqat O'Z kanallari),
           fail-soft (DB xatosi → istisno yo'q), no_channels/db_unavailable
           sabablari.
  TEST 8:  🖥 AI STUDIO / AUDIT EKRANLARI — AI Studio hub xabarida
           lokalizatsiya qilingan tavsiyalar bloki (haqiqiy handler +
           soxta DB); ``_content_learning_block(require_reco=True)`` audit
           uchun FAQAT aniq tavsiyalar bo'lganda blok qaytaradi; audit
           handler manbasida integratsiya mavjud.

Ishga tushirish:
    PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh   # runner bosqichi
    python3 tests/channel_dna2_content_learning_test.py
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
os.environ.setdefault("BOT_TOKEN", "123456:CHANNEL_DNA2_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10046")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("BETA_INVITE_ONLY", "false")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "telegram_bot"))
sys.path.insert(0, str(ROOT))

import database as db_mod  # noqa: E402
import handlers.ai_assistant as AI  # noqa: E402
from services.ai.orchestrator import AIOrchestrator  # noqa: E402
from services.ai.providers import AIProvider, ProviderChain  # noqa: E402
from services.channels.dna import (  # noqa: E402
    DEFAULT_TONE_PROMPTS,
    DNA_TONE_LABELS,
    MIN_POSTS_FOR_DNA,
    VOCABULARY_RULES,
    attach_dna_to_context,
    build_default_tone_prompt,
    build_dna_prompt_2,
    compute_channel_dna,
    compute_channel_dna_extended,
    normalize_dna_profile,
)
from services.channels.content_learning import (  # noqa: E402
    CONTENT_FORMATS,
    MIN_POSTS_FOR_LEARNING,
    PRIORITY_FORMATS,
    analyze_content_coverage,
    classify_post_formats,
    extract_post_text,
    get_content_learning_for_user,
    render_content_learning_text,
)
from translations import (  # noqa: E402
    CONTENT_LEARNING_KEYS,
    content_learning_parity_report,
    content_learning_t,
)
from utils.telegram_sanitizer import sanitize_html  # noqa: E402

USER_ID = 778001          # kanal EGASI
OTHER_USER_ID = 998877    # begona (IDOR)
CH_ID = "-1001234567890"
CH2_ID = "-1002222222222"
LANGS = ("uz", "ru", "en")

PASSED = 0
FAILURES = 0


def check(name, cond, extra=""):
    global PASSED, FAILURES
    if cond:
        PASSED += 1
        print(f"  [OK] {name}")
    else:
        FAILURES += 1
        print(f"  [FAIL] {name} {extra}")


def header(num, title):
    print(f"\n== TEST {num}: {title} ==")


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# DETERMINISTIK PROFILLAR (real hisob funksiyalari orqali)
# ---------------------------------------------------------------------------
def make_events(count=24, length=450, cta=True, with_text=True):
    events = []
    for i in range(count):
        ev = {
            "channel_id": CH_ID, "message_id": 5000 + i,
            "post_hour": 19 if i < 14 else 18,
            "post_weekday": 0 if i % 2 == 0 else 2,
            "has_media": i < 14, "media_type": "photo" if i < 14 else None,
            "length": length, "cta_detected": cta and i < count,
            "emoji_density": 0.009,
        }
        if with_text:
            ev["text"] = ("Futbol yangiliklari va mashqlar haqida foydali "
                          "ma'lumot bu yerda bor")
        events.append(ev)
    return events


LEGACY_PROFILE = compute_channel_dna(make_events())["profile"]
EXTENDED_PROFILE = compute_channel_dna_extended(make_events())["profile"]
THIN_PROFILE = dict(LEGACY_PROFILE, sample_size=3, confidence_score=0)

#: ``channel_dna`` jadvalidagi FLAT qator (get_channel_dna_profile surati).
FLAT_DNA_ROW = {
    "channel_id": CH_ID, "language": "ru", "tone": "formal",
    "topics": ["футбол"], "avg_length": 300, "emoji_density": 0.01,
    "best_hours": [19], "best_weekdays": [0],
    "high_performing_formats": ["photo"], "sample_size": 12,
    "confidence": 0.6, "profile": {}, "updated_at": "",
}

#: Real post matnlari (uz/ru/en) — kontent o'rganish uchun.
NEWS_POSTS = [
    {"text": "Bugun bozorda yangi mahsulot chiqdi — bu haqda xabar beramiz"},
    {"text": "Yangilik: kompaniya hisoboti e'lon qilindi, batafsil quyida"},
    {"text": "Sport yangiliklari: bugungi o'yin natijalari va jadval haqida"},
    {"text": "Yangi xabar: bozorda narxlar o'zgardi, tahlilni kuzatib boring"},
    {"text": "E'lon: kanal endi har kuni yangi xabarlar bilan ishlaydi"},
    {"text": "Bugungi yangiliklar sarlavhalari va qisqacha xabarlar to'plami"},
]
MIXED_POSTS = NEWS_POSTS[:2] + [
    {"text": "Savol-javob: ko'p beriladigan savol va javoblar ro'yxati"},
    {"text": "Пошаговая инструкция: шаг 1, шаг 2 — как сделать настройку"},
    {"text": "Client testimonial: our case study results and real feedback"},
    {"text": "Mijozimiz fikri: natijalarimiz haqida haqiqiy otziv va sharh"},
]


# ---------------------------------------------------------------------------
# SOXTA DB (run_db orqali; haqiqiy funksiyalarga tegmaydi)
# ---------------------------------------------------------------------------
class FakeDnaDB:
    """``attach_dna_to_context`` uchun minimal deterministik DB surati."""

    def __init__(self, owner=USER_ID, legacy=None, extended=None, boom=False):
        self.owner = owner
        self.legacy = legacy
        self.extended = extended
        self.boom = boom
        self.calls = []

    def get_channel_owner_id(self, channel_id):  # noqa: ARG002
        raise AssertionError("to'g'ridan-to'g'ri chaqirilmagani kerak")

    def get_channel_intelligence_profile(self, channel_id):  # noqa: ARG002
        raise AssertionError("to'g'ridan-to'g'ri chaqirilmagani kerak")

    def get_channel_dna_profile(self, channel_id):  # noqa: ARG002
        raise AssertionError("to'g'ridan-to'g'ri chaqirilmagani kerak")

    async def run_db(self, fn, *args, **kwargs):
        name = getattr(fn, "__name__", str(fn))
        self.calls.append(name)
        if self.boom:
            raise RuntimeError("DB down")
        if name == "get_channel_owner_id":
            return self.owner
        if name == "get_channel_intelligence_profile":
            return self.legacy
        if name == "get_channel_dna_profile":
            return self.extended
        raise AssertionError(f"kutilmagan db chaqiruvi: {name}")


class FakeLearningDB:
    """``get_content_learning_for_user`` uchun soxta DB (IDOR kuzatuvi bilan)."""

    def __init__(self, channels=None, posts=None, boom_history=False):
        self.channels = channels if channels is not None else {}
        self.posts = posts if posts is not None else {}
        self.boom_history = boom_history
        self.calls = []

    def get_user_channels(self, user_id):  # noqa: ARG002
        raise AssertionError("to'g'ridan-to'g'ri chaqirilmagani kerak")

    def get_channel_posts_history(self, channel_id, limit=25):  # noqa: ARG002
        raise AssertionError("to'g'ridan-to'g'ri chaqirilmagani kerak")

    async def run_db(self, fn, *args, **kwargs):
        name = getattr(fn, "__name__", str(fn))
        self.calls.append((name, args))
        if name == "get_user_channels":
            return self.channels.get(args[0], [])
        if name == "get_channel_posts_history":
            if self.boom_history:
                raise RuntimeError("history down")
            return self.posts.get(str(args[0]), [])
        raise AssertionError(f"kutilmagan db chaqiruvi: {name}")


class _CapturingProvider(AIProvider):
    """Orkestrator testida provayderga tushgan context'ni yozib oladi."""

    name = "CaptureProviderDNA2"

    def __init__(self):
        self.seen_ctx = None

    async def generate(self, prompt, context=None):
        self.seen_ctx = dict(context or {})
        return (
            "🔥 <b>Yangi mahsulot sotuvda!</b>\n\n"
            "Sifatli va qulay yechim. Hoziroq buyurtma bering!\n\n"
            "#yangilik #smm #toshkent"
        )


# ---------------------------------------------------------------------------
# Handler testlari uchun yengil fake'lar (tarmoqqa chiqmaydi)
# ---------------------------------------------------------------------------
class _Rec:
    def __init__(self, chat_id=4242, user_id=USER_ID):
        self.chat_id = chat_id
        self.from_user = SimpleNamespace(id=user_id, first_name="Tester")
        self.sent = []

    async def reply_text(self, text, **kwargs):
        self.sent.append(dict(text=text, **kwargs))
        return SimpleNamespace(message_id=1,
                               chat=SimpleNamespace(id=self.chat_id))


def _update_msg(rec):
    return SimpleNamespace(message=rec, effective_message=rec,
                           effective_user=rec.from_user, callback_query=None)


def _ctx(lang="uz"):
    return SimpleNamespace(
        user_data={"lang": lang}, chat_data={},
        bot=SimpleNamespace(username="dna2_test_bot"), application=None,
    )


def _patch_run_db(dispatch):
    """``database.run_db`` ni funksiya-nomi dispatch'i bilan almashtiradi."""
    orig = db_mod.run_db

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", str(fn))
        if callable(dispatch):
            return dispatch(name, args, kwargs)
        return (dispatch or {}).get(name)

    db_mod.run_db = fake_run_db
    return lambda: setattr(db_mod, "run_db", orig)


# ===========================================================================
# TEST 1 — 🧬 DNA 2.0 PROMPT BUILDER (tone + length + CTA + vocabulary)
# ===========================================================================
def test_dna2_prompt_builder():
    header("1", "🧬 DNA 2.0 — prompt bloki (tone/length/CTA/vocabulary)")

    markers = {
        "uz": ("KANAL USLUBI (DNA)", "450 belgi", "Uzunlik afzalligi:",
               "CTA uslubi:", "LUG'AT CHEKLOVLARI:"),
        "ru": ("СТИЛЬ КАНАЛА (DNA)", "Длина поста:", "Стиль CTA:",
               "ОГРАНИЧЕНИЯ ЛЕКСИКИ:"),
        "en": ("CHANNEL STYLE (DNA)", "Length preference:", "CTA style:",
               "VOCABULARY LIMITS:"),
    }
    for lang in LANGS:
        block = build_dna_prompt_2(LEGACY_PROFILE, lang)
        missing = [m for m in markers[lang] if m not in block]
        check(f"[{lang}] legacy profil: bazaviy kontrakt + 2.0 bo'limlari",
              not missing, f"missing={missing} block={block[:200]}")
        check(f"[{lang}] legacy: uzunlik afzalligi ±20% real sondan",
              "450" in block, block[:200])
        check(f"[{lang}] legacy: CTA ko'rsatmasi real cta_style'dan",
              ("har postda" in block.lower()) or ("cta" in block.lower()),
              block[:200])

    # Legacy profilda TONE yo'q → tone bo'limi UYDIRILMAYDI (NO FABRICATION).
    uz_legacy = build_dna_prompt_2(LEGACY_PROFILE, "uz")
    check("legacy: tone ma'lumoti yo'q → 'Ohang:' bo'limi YO'Q (uydirma yo'q)",
          "Ohang:" not in uz_legacy, uz_legacy[:240])

    # Kengaytirilgan profil — tone + topics + language REAL ma'lumotdan.
    uz_ext = build_dna_prompt_2(EXTENDED_PROFILE, "uz")
    check("extended: tone bo'limi real tasnifdan chiqdi",
          "Ohang:" in uz_ext
          and any(lbl in uz_ext for lbl in DNA_TONE_LABELS["uz"].values()),
          uz_ext[:260])
    check("extended: lug'at cheklovlari + kanal mavzulari (real topics)",
          "kanal mavzulariga yaqin so'zlar:" in uz_ext and "futbol" in uz_ext,
          uz_ext[-260:])
    ru_ext = build_dna_prompt_2(EXTENDED_PROFILE, "ru")
    en_ext = build_dna_prompt_2(EXTENDED_PROFILE, "en")
    check("extended: RU bo'limi 'Тон:' bilan", "Тон:" in ru_ext, ru_ext[:200])
    check("extended: EN bo'limi 'Tone:' bilan", "Tone:" in en_ext, en_ext[:200])

    # FLAT channel_dna qatori (nested profile bo'sh) — normalizatsiya ishlaydi.
    ru_flat = build_dna_prompt_2(FLAT_DNA_ROW, "ru")
    check("flat row: normalizatsiya → base + tone + length + vocab",
          "Тон: официальный" in ru_flat and "~300 символов" in ru_flat
          and "ОГРАНИЧЕНИЯ ЛЕКСИКИ" in ru_flat, ru_flat[:260])
    norm = normalize_dna_profile(FLAT_DNA_ROW)
    check("normalize: flat row → real maydonlar (tone/language/length)",
          norm.get("tone_value") == "formal" and norm.get("language_value") == "ru"
          and norm.get("average_post_length") == 300
          and norm.get("sample_size") == 12, str(norm))

    # CTA uslubi = none → "CTA qo'shmang" ko'rsatmasi (real kuzatuv).
    no_cta = dict(LEGACY_PROFILE, cta_style="none")
    uz_nocta = build_dna_prompt_2(no_cta, "uz")
    check("cta=none: 'CTA qo'shmang' ko'rsatmasi (uydirma CTA yo'q)",
          "CTA qo'shmang" in uz_nocta, uz_nocta[:260])

    # Kam ma'lumot / bo'sh profil → BO'SH (soxta uslub yo'q).
    for lang in LANGS:
        check(f"[{lang}] sample<{MIN_POSTS_FOR_DNA} → BO'SH (soxta uslub yo'q)",
              build_dna_prompt_2(THIN_PROFILE, lang) == "",
              build_dna_prompt_2(THIN_PROFILE, lang)[:120])
    check("bo'sh/None profil → BO'SH",
          build_dna_prompt_2({}, "uz") == "" and build_dna_prompt_2(None, "uz") == "")
    check("lug'at qoidalari 3 tilda to'liq (har tone uchun)",
          all(set(VOCABULARY_RULES[lang]) >= set(DNA_TONE_LABELS[lang]) | {"_default"}
              for lang in LANGS))


# ===========================================================================
# TEST 2 — 🛟 GRACEFUL FALLBACK: STANDART OHANG (DNA tahlil qilinmagan)
# ===========================================================================
def test_default_tone_fallback():
    header("2", "🛟 Standart ohang fallback (uz/ru/en, xatosiz, soxtasiz)")
    blocks = {lang: build_default_tone_prompt(lang) for lang in LANGS}
    for lang in LANGS:
        block = blocks[lang]
        check(f"[{lang}] standart ohang bloki bo'sh emas", bool(block.strip()))
        check(f"[{lang}] 'DNA' so'zi YO'Q (IDOR kontrakti)", "DNA" not in block, block)
        check(f"[{lang}] legacy header YO'Q", "KANAL USLUBI" not in block, block)
        check(f"[{lang}] soxta raqam YO'Q (belgi/foiz)",
              "%" not in block and "belgi)" not in block, block)
    check("3 til bloklari o'zaro farqli",
          len({blocks[lang] for lang in LANGS}) == 3)
    check("noma'lum til → uz fallback (xatosiz)",
          build_default_tone_prompt("xx") == DEFAULT_TONE_PROMPTS["uz"])
    check("DEFAULT_TONE_PROMPTS 3 tilda mavjud",
          set(DEFAULT_TONE_PROMPTS) >= {"uz", "ru", "en"})


# ===========================================================================
# TEST 3 — 🔌 attach_dna_to_context (DNA 2.0 + fallback + IDOR + fail-soft)
# ===========================================================================
def test_attach_dna_context():
    header("3", "🔌 attach_dna_to_context — 2.0, fallback, IDOR, fail-soft")

    # 3a) OWNER + legacy profil → DNA 2.0 to'liq blok.
    fake = FakeDnaDB(owner=USER_ID, legacy=LEGACY_PROFILE)
    ctx = {"channel_id": CH_ID, "system_prompt": "BASE_MARKER", "lang": "uz"}
    run(attach_dna_to_context(ctx, USER_ID, fake))
    sp = ctx.get("system_prompt", "")
    check("owner+legacy: BASE saqlandi", "BASE_MARKER" in sp, sp[:160])
    check("owner+legacy: DNA 2.0 ulandi (header + vocab bo'limi)",
          "KANAL USLUBI (DNA)" in sp and "LUG'AT CHEKLOVLARI:" in sp, sp[:240])
    check("owner+legacy: channel_dna_attached=True",
          ctx.get("channel_dna_attached") is True)
    check("owner+legacy: default_tone flag YO'Q",
          ctx.get("channel_dna_default_tone") is None)

    # 3b) OWNER + profil YO'Q → GRACEFUL FALLBACK (standart ohang, xatosiz).
    fake = FakeDnaDB(owner=USER_ID, legacy=None)
    ctx = {"channel_id": CH_ID, "system_prompt": "BASE_MARKER", "lang": "uz"}
    run(attach_dna_to_context(ctx, USER_ID, fake))
    sp = ctx.get("system_prompt", "")
    check("owner+profilsiz: standart ohang ulandi (fallback)",
          DEFAULT_TONE_PROMPTS["uz"] in sp and "BASE_MARKER" in sp, sp[:200])
    check("owner+profilsiz: channel_dna_default_tone=True",
          ctx.get("channel_dna_default_tone") is True)
    check("owner+profilsiz: DNA header YO'Q (soxta profil yo'q)",
          "KANAL USLUBI (DNA)" not in sp, sp[:200])
    check("owner+profilsiz: channel_dna_attached YO'Q",
          ctx.get("channel_dna_attached") is None)

    # 3c) OWNER + yupqa profil (sample 3) → fallback (soxta uslub yo'q).
    fake = FakeDnaDB(owner=USER_ID, legacy=THIN_PROFILE)
    ctx = {"channel_id": CH_ID, "system_prompt": "BASE", "lang": "ru"}
    run(attach_dna_to_context(ctx, USER_ID, fake))
    sp = ctx.get("system_prompt", "")
    check("owner+thin: RU standart ohang fallback",
          DEFAULT_TONE_PROMPTS["ru"] in sp, sp[:200])
    check("owner+thin: DNA ulanmadi", "KANAL USLUBI (DNA)" not in sp
          and ctx.get("channel_dna_attached") is None, sp[:160])

    # 3d) IDOR — begona kanal: kontekst O'ZGARMAYDI (fallback ham yo'q).
    fake = FakeDnaDB(owner=USER_ID, legacy=None)
    ctx = {"channel_id": CH_ID, "system_prompt": "BASE", "lang": "uz"}
    run(attach_dna_to_context(ctx, OTHER_USER_ID, fake))
    check("IDOR: begona kanal prompti O'ZGARMADI",
          ctx.get("system_prompt") == "BASE", str(ctx))
    check("IDOR: hech qanday flag qo'shilmadi",
          "DNA" not in ctx.get("system_prompt", "")
          and ctx.get("channel_dna_default_tone") is None, str(ctx))

    # 3e) skip_dna / channel_id'siz — kontekst tegilmaydi.
    fake = FakeDnaDB(owner=USER_ID, legacy=LEGACY_PROFILE)
    ctx = {"channel_id": CH_ID, "system_prompt": "BASE", "lang": "uz",
           "skip_dna": True}
    run(attach_dna_to_context(ctx, USER_ID, fake))
    check("skip_dna: kontekst o'zgarmadi", ctx.get("system_prompt") == "BASE")
    ctx = {"system_prompt": "BASE", "lang": "uz"}
    run(attach_dna_to_context(ctx, USER_ID, fake))
    check("channel_id'siz: kontekst o'zgarmadi (fallback ham yo'q)",
          ctx.get("system_prompt") == "BASE", str(ctx))

    # 3f) KENGAYTIRILGAN profil PRIORITETI: channel_dna (tone bilan) afzal.
    ext_row = dict(FLAT_DNA_ROW)
    fake = FakeDnaDB(owner=USER_ID, legacy=LEGACY_PROFILE, extended=ext_row)
    ctx = {"channel_id": CH_ID, "system_prompt": "BASE", "lang": "ru"}
    run(attach_dna_to_context(ctx, USER_ID, fake))
    sp = ctx.get("system_prompt", "")
    check("extended prioritet: tone bo'limi channel_dna dan",
          "Тон: официальный" in sp, sp[:260])
    check("extended prioritet: legacy profil ham zaxira (header bor)",
          "ДНК КАНАЛА" in sp or "СТИЛЬ КАНАЛА" in sp, sp[:200])

    # 3g) FAIL-SOFT: DB xatosi → istisno yo'q, generatsiya konteksti butun.
    fake = FakeDnaDB(owner=USER_ID, legacy=LEGACY_PROFILE, boom=True)
    ctx = {"channel_id": CH_ID, "system_prompt": "BASE", "lang": "uz"}
    run(attach_dna_to_context(ctx, USER_ID, fake))  # istisno ko'tarilmaydi
    check("DB down: fail-soft (BASE saqlandi, istisno yo'q)",
          ctx.get("system_prompt") == "BASE", str(ctx))

    # 3h) EN fallback tili.
    fake = FakeDnaDB(owner=USER_ID, legacy=None)
    ctx = {"channel_id": CH_ID, "system_prompt": "BASE", "lang": "en"}
    run(attach_dna_to_context(ctx, USER_ID, fake))
    check("EN: standart ohang fallback ingliz tilida",
          DEFAULT_TONE_PROMPTS["en"] in ctx.get("system_prompt", ""),
          str(ctx)[:200])


# ===========================================================================
# TEST 4 — 🤖 ORKESTRATOR END-TO-END (DNA 2.0 + fallback generatsiyada)
# ===========================================================================
def test_orchestrator_integration():
    header("4", "🤖 AIOrchestrator — DNA 2.0 va fallback provayder kontekstida")

    async def _go(fake, profile_present):
        prov = _CapturingProvider()
        result = await AIOrchestrator(
            provider_chain=ProviderChain(providers=[prov])
        ).orchestrate(
            user_id=USER_ID, prompt="Post yoz", lang="uz",
            context={"channel_id": CH_ID, "system_prompt": "BASE_PROMPT_MARKER",
                     "skip_quota": True, "skip_queue": True},
            db_module=fake,
        )
        return result, prov.seen_ctx or {}

    fake = FakeDnaDB(owner=USER_ID, legacy=LEGACY_PROFILE)
    res, seen = run(_go(fake, True))
    sp = seen.get("system_prompt", "")
    check("orchestrator[DNA]: generatsiya muvaffaqiyatli", res.success is True,
          str(getattr(res, "error_code", None)))
    check("orchestrator[DNA]: DNA 2.0 provayder kontekstida",
          "KANAL USLUBI (DNA)" in sp and "LUG'AT CHEKLOVLARI:" in sp, sp[:220])
    check("orchestrator[DNA]: flag channel_dna_attached",
          seen.get("channel_dna_attached") is True)

    fake2 = FakeDnaDB(owner=USER_ID, legacy=None)
    res2, seen2 = run(_go(fake2, False))
    sp2 = seen2.get("system_prompt", "")
    check("orchestrator[fallback]: generatsiya muvaffaqiyatli (xatosiz)",
          res2.success is True, str(getattr(res2, "error_code", None)))
    check("orchestrator[fallback]: standart ohang kontekstda",
          DEFAULT_TONE_PROMPTS["uz"] in sp2 and "BASE_PROMPT_MARKER" in sp2,
          sp2[:220])
    check("orchestrator[fallback]: channel_dna_default_tone=True",
          seen2.get("channel_dna_default_tone") is True)
    check("orchestrator[fallback]: soxta DNA yo'q",
          "KANAL USLUBI (DNA)" not in sp2, sp2[:200])


# ===========================================================================
# TEST 5 — 📚 CONTENT LEARNING (PURE): tasnif + gap deteksiya + NO FABRICATION
# ===========================================================================
def test_content_learning_pure():
    header("5", "📚 Content learning — format tasnifi va gap deteksiya")

    # 5a) Format tasnifi — uchala tilda (Q&A / tutorial / social proof).
    check("classify[uz]: savol-javob → qa",
          "qa" in classify_post_formats(
              "Savol-javob: ko'p beriladigan savol va javoblar ro'yxati"))
    check("classify[ru]: инструкция → tutorial",
          "tutorial" in classify_post_formats(
              "Пошаговая инструкция: шаг 1, шаг 2 — как сделать настройку"))
    check("classify[en]: testimonial → social_proof",
          "social_proof" in classify_post_formats(
              "Client testimonial: our case study results and real feedback"))
    check("classify: qisqa matn (<20) tasniflanmaydi",
          classify_post_formats("savol") == set())
    check("classify: bo'sh/None → bo'sh to'plam",
          classify_post_formats("") == set() and classify_post_formats(None) == set())

    # 5b) extract_post_text — dict/tuple/str shakllari (fail-soft).
    check("extract: dict text/content",
          extract_post_text({"text": "abc"}) == "abc"
          and extract_post_text({"content": "xyz"}) == "xyz")
    check("extract: tuple qator (content 3-indeksda)",
          extract_post_text((1, CH_ID, 2, "post matni", 0, "")) == "post matni")
    check("extract: noto'g'ri qator → bo'sh",
          extract_post_text(object()) == "" and extract_post_text(None) == "")

    # 5c) Gap deteksiya — faqat news bo'lsa: Q&A/tutorial/social_proof yo'q.
    report = analyze_content_coverage(NEWS_POSTS)
    check("analyze: yetarli ma'lumot (6 post)",
          report["insufficient"] is False and report["sample_size"] == 6,
          str(report))
    check("analyze: observed REAL sonlar (news=6)",
          report["observed"].get("news") == 6, str(report["observed"]))
    check("analyze: missing — prioritetsiz formatlar emas, PRIORITET birinchi",
          report["missing"][:3] == list(PRIORITY_FORMATS)
          and all(f in CONTENT_FORMATS for f in report["missing"]),
          str(report["missing"]))
    check("analyze: tavsiyalar cheklangan (≤4)",
          0 < len(report["recommendations"]) <= 4, str(report["recommendations"]))
    check("analyze: news observed → missing'da YO'Q",
          "news" not in report["missing"], str(report["missing"]))

    # 5d) Aralash postlar — kuzatilgan formatlar tavsiyadan CHIQADI.
    mixed = analyze_content_coverage(MIXED_POSTS)
    check("mixed: qa/tutorial/social_proof kuzatildi",
          all(f in mixed["observed"] for f in PRIORITY_FORMATS),
          str(mixed["observed"]))
    check("mixed: kuzatilgan formatlar tavsiyalarda YO'Q",
          not (set(mixed["recommendations"]) & set(mixed["observed"])),
          str(mixed["recommendations"]))

    # 5e) NO FABRICATION — kam ma'lumotda tavsiya YO'Q, sonlar REAL.
    thin = analyze_content_coverage(NEWS_POSTS[:3])
    check("insufficient: 3 post → insufficient=True",
          thin["insufficient"] is True and thin["sample_size"] == 3
          and thin["min_posts"] == MIN_POSTS_FOR_LEARNING, str(thin))
    check("insufficient: tavsiyalar BO'SH (soxta tavsiya yo'q)",
          thin["recommendations"] == [] and thin["missing"] == [], str(thin))
    empty = analyze_content_coverage([])
    check("bo'sh ro'yxat → insufficient (sample 0)",
          empty["insufficient"] is True and empty["sample_size"] == 0, str(empty))
    junk = analyze_content_coverage([{"text": "ha"} for _ in range(9)])
    check("juda qisqa matnlar hisoblanmaydi (halol sample)",
          junk["insufficient"] is True and junk["sample_size"] == 0, str(junk))


# ===========================================================================
# TEST 6 — 🌍 RENDER + UZ/RU/EN 100% PARITET
# ===========================================================================
def test_render_and_i18n_parity():
    header("6", "🌍 Render — uchala tilda paritet va halol xabarlar")

    report = analyze_content_coverage(NEWS_POSTS)
    report["ok"] = True
    report["channels_analyzed"] = 2
    renders = {lang: render_content_learning_text(report, lang) for lang in LANGS}
    titles = {"uz": "KONTENT O'RGANISH", "ru": "ОБУЧЕНИЕ КОНТЕНТА",
              "en": "CONTENT LEARNING"}
    for lang in LANGS:
        text = renders[lang]
        check(f"render[{lang}]: sarlavha lokal", titles[lang] in text, text[:120])
        check(f"render[{lang}]: REAL sonlar (6 post, 2 kanal)",
              "6" in text and "2" in text, text[:220])
        check(f"render[{lang}]: Q&A tavsiyasi lokal",
              content_learning_t("cl_reco_qa", lang) in text, text[-320:])
        check(f"render[{lang}]: halol manba eslatmasi (footer)",
              content_learning_t("cl_footer", lang) in text, text[-200:])
    check("render: 3 til matnlari o'zaro farqli",
          len(set(renders.values())) == 3)

    # Insufficient — halol xabar (real n/min), tavsiya bulletlari YO'Q.
    thin = analyze_content_coverage(NEWS_POSTS[:2])
    for lang in LANGS:
        text = render_content_learning_text(thin, lang)
        check(f"insufficient[{lang}]: halol xabar (real 2/5 sonlari)",
              "2" in text and "5" in text, text)
        check(f"insufficient[{lang}]: tavsiya bulletlari YO'Q",
              content_learning_t("cl_missing_header", lang) not in text, text)
        check(f"insufficient[{lang}]: soxta foiz YO'Q", "%" not in text, text)

    # no_channels sababi — alohida halol xabar.
    for lang in LANGS:
        text = render_content_learning_text(
            {"insufficient": True, "sample_size": 0, "reason": "no_channels"}, lang)
        check(f"no_channels[{lang}]: kanal ulash ko'rsatmasi",
              content_learning_t("cl_no_channels", lang) in text, text)

    # i18n PARITET — kalitlar + format argumentlari (uz↔ru↔en).
    parity = content_learning_parity_report()
    check("parity: in_sync=True", parity["in_sync"] is True, str(parity))
    check("parity: missing/extra yo'q",
          not any(parity["missing"].values())
          and not any(parity["extra"].values()), str(parity))
    check("parity: format argumentlari bir xil ({n}/{min}/{channels}/{count})",
          not parity["format_mismatch"], str(parity["format_mismatch"]))
    check("parity: bo'sh qiymat yo'q", not parity["empty"], str(parity["empty"]))
    check("parity: barcha formatlar uchun label+tavsiya kalitlari bor",
          all(f"cl_format_{f}" in CONTENT_LEARNING_KEYS
              and f"cl_reco_{f}" in CONTENT_LEARNING_KEYS
              for f in CONTENT_FORMATS))
    for lang in LANGS:
        check(f"t[{lang}]: har kalit bo'sh emas",
              all(content_learning_t(k, lang).strip() for k in CONTENT_LEARNING_KEYS))
    check("t: noma'lum kalit → uz jadvaliga fallback",
          content_learning_t("cl_title", "xx") == content_learning_t("cl_title", "uz"))
    check("t: formatlash ishlaydi (cl_insufficient {n}/{min})",
          "3" in content_learning_t("cl_insufficient", "uz", n=3, min=5)
          and "5" in content_learning_t("cl_insufficient", "ru", n=3, min=5)
          and "3" in content_learning_t("cl_insufficient", "en", n=3, min=5))


# ===========================================================================
# TEST 7 — 🔐 get_content_learning_for_user (IDOR + fail-soft)
# ===========================================================================
def test_learning_service_idor():
    header("7", "🔐 Service — IDOR (faqat o'z kanallari) va fail-soft")

    fake = FakeLearningDB(
        channels={USER_ID: [(CH_ID, "Kanal A"), (CH2_ID, "Kanal B")]},
        posts={CH_ID: NEWS_POSTS[:4], CH2_ID: NEWS_POSTS[4:]},
    )
    rep = run(get_content_learning_for_user(USER_ID, "uz", db_module=fake))
    check("owner: ok=True, insufficient=False",
          rep.get("ok") is True and rep.get("insufficient") is False, str(rep))
    check("owner: 2 kanal tahlil qilindi (REAL son)",
          rep.get("channels_analyzed") == 2, str(rep))
    check("owner: sample_size=6 (ikki kanal postlari)",
          rep.get("sample_size") == 6, str(rep))
    ch_calls = [c[1][0] for c in fake.calls if c[0] == "get_channel_posts_history"]
    check("IDOR: tarix FAQAT o'z kanallaridan so'raldi",
          set(ch_calls) == {CH_ID, CH2_ID}, str(ch_calls))

    other = run(get_content_learning_for_user(OTHER_USER_ID, "uz", db_module=fake))
    check("begona foydalanuvchi: kanallari yo'q → no_channels",
          other.get("reason") == "no_channels" and other.get("ok") is True,
          str(other))
    check("begona: tavsiyalar BO'SH (soxta tavsiya yo'q)",
          other.get("recommendations") == [], str(other))

    boom = FakeLearningDB(channels={USER_ID: [(CH_ID, "A")]}, boom_history=True)
    rep_boom = run(get_content_learning_for_user(USER_ID, "uz", db_module=boom))
    check("history down: fail-soft (insufficient, istisno yo'q)",
          rep_boom.get("ok") is True and rep_boom.get("insufficient") is True
          and rep_boom.get("sample_size") == 0, str(rep_boom))

    class NoChannelsFn:
        async def run_db(self, fn, *args, **kwargs):  # noqa: ARG002
            return None

    rep_noch = run(get_content_learning_for_user(USER_ID, "uz",
                                                 db_module=NoChannelsFn()))
    check("get_user_channels yo'q → db_unavailable (fail-closed sabab)",
          rep_noch.get("reason") == "db_unavailable", str(rep_noch))
    rep_uid = run(get_content_learning_for_user(None, "uz", db_module=fake))
    check("user_id=None → no_user (istisno yo'q)",
          rep_uid.get("reason") == "no_user", str(rep_uid))


# ===========================================================================
# TEST 8 — 🖥 AI STUDIO / AUDIT EKRANLARI INTEGRATSIYASI
# ===========================================================================
def test_studio_and_audit_screens():
    header("8", "🖥 AI Studio hub + Audit ekrani — lokal tavsiyalar")

    # 8a) AI Studio hub — haqiqiy handler, soxta DB: tavsiyalar BIR xabarda.
    dispatch = {
        "is_premium": False,
        "get_user_credits": 7,
        "get_user_channels": [(CH_ID, "Kanal A")],
        "get_channel_posts_history": NEWS_POSTS,
    }
    restore = _patch_run_db(dispatch)
    try:
        for lang in LANGS:
            rec = _Rec()
            state = run(AI.ai_studio_hub_entry(_update_msg(rec), _ctx(lang)))
            check(f"[{lang}] hub: AI_MENU_STATE + bitta xabar",
                  state == AI.AI_MENU_STATE and len(rec.sent) == 1,
                  f"{state} {len(rec.sent)}")
            text = rec.sent[0]["text"] if rec.sent else ""
            check(f"[{lang}] hub: KONTENT O'RGANISH bloki xabarda",
                  content_learning_t("cl_title", lang) in text, text[:200])
            # Eslatma: handler blokcasi sanitize_html dan o'tadi ("&" → "&amp;")
            # — kutilgan matn ham XUDDI SHU sanitizer orqali taqqoslanadi.
            check(f"[{lang}] hub: Q&A tavsiyasi ko'rsatildi",
                  sanitize_html(content_learning_t("cl_reco_qa", lang), None)
                  in text, text[-300:])
            check(f"[{lang}] hub: klaviatura O'ZGARMADI (7 tugma)",
                  len([b for row in rec.sent[0]["reply_markup"].inline_keyboard
                       for b in row]) == 7)
    finally:
        restore()

    # 8b) Hub — kanal ulanmagan: HALOL ko'rsatma (soxta metrika yo'q).
    restore = _patch_run_db({"is_premium": False, "get_user_credits": 3,
                             "get_user_channels": []})
    try:
        rec = _Rec()
        run(AI.ai_studio_hub_entry(_update_msg(rec), _ctx("uz")))
        text = rec.sent[0]["text"] if rec.sent else ""
        check("hub[kanalsiz]: halol 'kanal ulang' ko'rsatmasi",
              content_learning_t("cl_no_channels", "uz") in text, text[-200:])
    finally:
        restore()

    # 8c) Hub — DB xatosi: menyu buzilmaydi (fail-soft, istisno yo'q).
    def _boom(name, args, kwargs):
        if name in ("get_user_channels", "get_channel_posts_history"):
            raise RuntimeError("DB down")
        return {"is_premium": False, "get_user_credits": 5}.get(name)

    restore = _patch_run_db(_boom)
    try:
        rec = _Rec()
        state = run(AI.ai_studio_hub_entry(_update_msg(rec), _ctx("uz")))
        check("hub[DB down]: fail-soft — menyu chiqdi, istisno yo'q",
              state == AI.AI_MENU_STATE and len(rec.sent) == 1, str(state))
    finally:
        restore()

    # 8d) Audit bloki yordamchisi — require_reco semantikasi.
    restore = _patch_run_db({
        "get_user_channels": [(CH_ID, "Kanal A")],
        "get_channel_posts_history": NEWS_POSTS,
    })
    try:
        block_audit = run(AI._content_learning_block(USER_ID, "uz",
                                                     require_reco=True))
        check("audit helper: tavsiyalar bor → blok qaytdi",
              bool(block_audit)
              and sanitize_html(content_learning_t("cl_reco_qa", "uz"), None)
              in block_audit, block_audit[:160])
    finally:
        restore()

    restore = _patch_run_db({
        "get_user_channels": [(CH_ID, "Kanal A")],
        "get_channel_posts_history": NEWS_POSTS[:2],
    })
    try:
        block_audit_thin = run(AI._content_learning_block(USER_ID, "uz",
                                                          require_reco=True))
        block_hub_thin = run(AI._content_learning_block(USER_ID, "uz"))
        check("audit helper: insufficient → BO'SH (audit toza qoladi)",
              block_audit_thin == "", block_audit_thin[:120])
        check("hub helper: insufficient → halol xabar (bo'sh emas)",
              content_learning_t("cl_insufficient", "uz", n=2,
                                 min=MIN_POSTS_FOR_LEARNING) in block_hub_thin,
              block_hub_thin[:160])
    finally:
        restore()

    # 8e) Manba kontrakti: audit handlerida integratsiya mavjud.
    src = (ROOT / "telegram_bot" / "handlers" / "ai_assistant.py").read_text(
        encoding="utf-8")
    check("audit manba: _content_learning_block(require_reco=True) ulangan",
          "require_reco=True" in src)
    check("audit manba: 4096 himoyasi (audit_limit kichrayadi)",
          "audit_limit = 2600 if learning_block else 3500" in src)
    check("studio manba: hub entry learning blokni ulaydi",
          "learning_block = await _content_learning_block(user_id, lang)" in src)


# ===========================================================================
def main():
    print("=" * 70)
    print(" 🧪 STEP 3 — CHANNEL DNA 2.0 & CONTENT LEARNING INTEGRATION")
    print("=" * 70)
    test_dna2_prompt_builder()
    test_default_tone_fallback()
    test_attach_dna_context()
    test_orchestrator_integration()
    test_content_learning_pure()
    test_render_and_i18n_parity()
    test_learning_service_idor()
    test_studio_and_audit_screens()

    print("\n" + "=" * 70)
    print(f" JAMI: o'tdi={PASSED}, xato={FAILURES}")
    if FAILURES:
        print(" [FAIL] CHANNEL DNA 2.0 & CONTENT LEARNING TESTDA XATOLIKLAR BOR ^^^")
        return 1
    print(" STEP 3 (DNA 2.0 + CONTENT LEARNING) — 100% YASHIL ✔")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
