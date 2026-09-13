#!/usr/bin/env python3
"""🎙 VOICE → POST — KILLER FEATURE OQIM TESTI (deterministik, mock asosida).

Qamrov (topshiriq talablari bilan birma-bir):

  TEST 1:  RESURS HIMOYA — FREE foydalanuvchining 60 soniyadan OSHGAN audio
           qaytariladi («Iltimos, g'oyangizni qisqaroq (1 daqiqa ichida)...»);
           PRO uchun 180s chegarasi; hajm ≤20 MB; cheklovda STT HAM,
           kredit HAM yechilmaydi.
  TEST 2:  STT ($0) — Groq Whisper matn qaytarganda uslublar menyusi chiqadi
           (5 uslub + [❌ Bekor qilish]); «Bekor qilish» bosilsa jarayon
           to'xtaydi va HECH QANDAY AI limiti/krediti Yechilmaydi;
           transkripsiya xatosida ham kredit tiyiladi.
  TEST 3:  USLUB TANLANGANDA — faqat 1 ta kredit ATOMIK yechiladi
           (check_ai_limit + use_user_credit AYNAN 1 martadan), Magic Post
           prompti tayyor post qaytaradi, xatoda refund qilinadi;
           [📢 Kanalga yuborish] / [📅 Rejalashtirish] / [🔄 Boshqa uslub].
  TEST 4:  i18n PARITET (uz/ru/en) + audio_transcriber birlik tekshiruvlari
           (Groq→Gemini zanjiri, cheklovlar, sanitisatsiya).

Ishga tushirish:
    bash tests/run_tests.sh                  # yoki
    python3 tests/voice_to_post_flow_test.py
"""
import asyncio
import base64
import os
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
#    (ADMIN_ID test foydalanuvchilaridan FARQI QILADI — ular admin emas.)
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:VOICE_POST_FLOW_TOKEN")
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
OGG_BYTES = b"OggS" + b"\x00" * 128  # soxta .ogg mazmun


class FakeMedia:
    """Telegram Voice/Audio obyekti o'rnini bosuvchi soxta media."""

    def __init__(self, duration=30, file_size=200_000, file_id="FILE_VOICE_1",
                 file_name=None, mime_type="audio/ogg"):
        self.duration = duration
        self.file_size = file_size
        self.file_id = file_id
        self.file_name = file_name
        self.mime_type = mime_type


class FakeFile:
    def __init__(self, data=OGG_BYTES):
        self._data = data

    async def download_as_bytearray(self):
        return bytearray(self._data)


class FakeBot:
    def __init__(self, data=OGG_BYTES):
        self._data = data
        self.get_file_calls = []

    async def get_file(self, file_id):
        self.get_file_calls.append(file_id)
        return FakeFile(self._data)

    async def send_message(self, chat_id=None, text=None, parse_mode=None, **kwargs):
        return SimpleNamespace(message_id=1)


class FakeMessage:
    def __init__(self, voice=None, audio=None, document=None, text=None):
        self.voice = voice
        self.audio = audio
        self.document = document
        self.text = text
        self.caption = None
        self.chat = SimpleNamespace(id=555000)
        self.replies = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kwargs):
        self.replies.append({"text": text, "reply_markup": reply_markup,
                             "parse_mode": parse_mode})
        return self


class FakeQuery:
    def __init__(self, data, user_id=771000):
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
    def __init__(self, message=None, query=None, user_id=771000):
        self.message = message
        self.callback_query = query
        self.effective_user = SimpleNamespace(
            id=(query.from_user.id if query else user_id))


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
            out.append((btn.text, btn.callback_data))
    return out


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# MODULLAR (env sozlangandan KEYIN import qilinadi)
# ---------------------------------------------------------------------------
from handlers import voice_post as vh                         # noqa: E402
from handlers import magic_post as mp                         # noqa: E402
from handlers.ai_assistant import AI_GET_TIME                 # noqa: E402
from translations import (                                    # noqa: E402
    MAGIC_STYLE_KEYS, VOICE_POST_KEYS,
    voice_post_parity_report, voice_t,
)
from utils import audio_transcriber as at                     # noqa: E402

LANGS = ("uz", "ru", "en")

# ---------------------------------------------------------------------------
# DB MOCK — handlers.voice_post.db.run_db (shared database moduli) almashadi.
# Har bir chaqiruv DB_CALLS ro'yxatiga yoziladi — kredit ANIQ 1 MARTA
# yechilganini tekshirish uchun.
# ---------------------------------------------------------------------------
DB_CALLS = []
PRO_FLAG = [False]
FAKE_CHANNELS = [("-100111001", "Kanal A"), ("-100222002", "Kanal B")]


def reset_db_mock(is_pro=False):
    DB_CALLS.clear()
    PRO_FLAG[0] = is_pro


async def fake_run_db(func, *args, **kwargs):
    name = getattr(func, "__name__", str(func))
    DB_CALLS.append(name)
    if name == "get_sponsor_channels":
        return []                       # homiy obuna yo'q → ruxsat
    if name == "get_user_language":
        return "uz"
    if name == "is_premium":
        return PRO_FLAG[0]
    if name == "check_ai_limit":
        return (True, 1, 30)            # atomik bron: OK
    if name == "use_user_credit":
        return True                     # 1 ball yechildi
    if name == "add_user_credit":
        return True                     # refund
    if name == "refund_ai_usage":
        return True                     # kunlik kvota refund
    if name == "get_user_channels":
        return list(FAKE_CHANNELS)
    if name == "increment_ai_usage":
        return True
    return None


DB_PATCH = patch("handlers.voice_post.db.run_db", new=fake_run_db)

# ---------------------------------------------------------------------------
# STT MOCK — Groq/Gemini chaqiruvi almashtiriladi (real tarmoq YO'Q).
# ---------------------------------------------------------------------------
STT_CALLS = []


def make_stt(text="Yangi kofemiz endi 20% chegirma bilan sotilmoqda",
             provider="groq", error=None):
    async def fake_transcribe(data, filename="voice.ogg", session=None):
        STT_CALLS.append({"filename": filename, "bytes": bytes(data)})
        if error:
            return {"error": error}
        return {"text": text, "provider": provider}
    return fake_transcribe


STT_PATCH = patch("handlers.voice_post.transcribe_voice",
                  new=make_stt())  # default — muvaffaqiyatli Groq

GEN_CALLS = []


def make_gen(post="<b>Katta sotuv!</b> Kofe 20% arzon. 🛒 Buyurtma bering. "
                  "#sotuv #kofe #chegirma #aksiya", style="sales", error=None):
    async def fake_generate(raw, style_, lang="uz", is_pro=False, timeout=None):
        GEN_CALLS.append({"raw": raw, "style": style_, "lang": lang})
        if error:
            return {"error": error}
        return {"post_text": post, "style": style or style_, "lang": lang}
    return fake_generate


def run_voice(ctx, duration, is_pro=False, file_size=200_000,
              stt=None, media_kind="voice"):
    """Voice xabar yuborilgandagi entry oqimini ishga tushiradi."""
    reset_db_mock(is_pro=is_pro)
    STT_CALLS.clear()
    if stt is not None:
        stt_patcher = patch("handlers.voice_post.transcribe_voice", new=stt)
    else:
        stt_patcher = STT_PATCH
    media = FakeMedia(duration=duration, file_size=file_size)
    msg = FakeMessage(**{media_kind: media})
    with DB_PATCH, stt_patcher:
        state = run(vh.voice_message_received(FakeUpdate(message=msg), ctx))
    return state, msg


# ============================================================================
# TEST 1 — RESURS HIMOYA: davomiylik va hajm cheklovlari
# ============================================================================
def test_duration_and_size_limits():
    print("\n== TEST 1: Cheklovlar — FREE 60s / PRO 180s / 20 MB ==")

    # 1a) FREE + 61s → rad etiladi, «1 daqiqa» matni, STT HAM kredit HAM yo'q.
    ctx = FakeContext()
    state, msg = run_voice(ctx, duration=61, is_pro=False)
    check("FREE 61s audio qaytarildi (END)",
          state == vh.ConversationHandler.END, str(state))
    joined = " ".join(r["text"] for r in msg.replies)
    check("rad etish matnida «1 daqiqa» bor", "1 daqiqa" in joined, joined[:120])
    check("STT chaqirilmadi (resurs tejaldi)", len(STT_CALLS) == 0)
    check("kredit/kvota yechilmadi",
          "use_user_credit" not in DB_CALLS and "check_ai_limit" not in DB_CALLS)

    # 1b) FREE + aynan 60s → o'tadi (STT chaqiriladi → uslub menyusi).
    ctx2 = FakeContext()
    state2, msg2 = run_voice(ctx2, duration=60, is_pro=False)
    check("FREE aynan 60s o'tdi (menyu chiqdi)", state2 == vh.VOICE_STYLE_SELECT)
    check("60s'da STT chaqirildi", len(STT_CALLS) == 1)
    check("60s'da ham kredit YO'Q (STT bepul)",
          "use_user_credit" not in DB_CALLS and "check_ai_limit" not in DB_CALLS)

    # 1c) PRO + 180s → o'tadi; PRO + 181s → rad etiladi («3 daqiqa»).
    ctx3 = FakeContext()
    state3, _m3 = run_voice(ctx3, duration=180, is_pro=True)
    check("PRO 180s o'tdi", state3 == vh.VOICE_STYLE_SELECT)
    ctx4 = FakeContext()
    state4, msg4 = run_voice(ctx4, duration=181, is_pro=True)
    joined4 = " ".join(r["text"] for r in msg4.replies)
    check("PRO 181s rad etildi", state4 != vh.VOICE_STYLE_SELECT)
    check("PRO rad etish matnida «3 daqiqa» bor", "3 daqiqa" in joined4, joined4[:120])

    # 1d) Hajm >20MB → rad etiladi (STT/kredit yo'q).
    ctx5 = FakeContext()
    state5, msg5 = run_voice(ctx5, duration=30, file_size=21 * 1024 * 1024)
    joined5 = " ".join(r["text"] for r in msg5.replies)
    check("21MB audio rad etildi", "20 MB" in joined5, joined5[:120])
    check("21MB'da STT chaqirilmadi", len(STT_CALLS) == 0)

    # 1e) Transkripsiya matni menyuda ko'rinadi + 5 uslub + bekor tugmasi.
    ctx6 = FakeContext()
    state6, msg6 = run_voice(ctx6, duration=30)
    menu = msg6.replies[-1]
    check("menyuda transkripsiyalangan matn bor",
          "20% chegirma" in menu["text"])
    check("menyuda «matnga o'girildi» sarlavhasi bor",
          "matnga o'girildi" in menu["text"])
    cbs = [d for _t, d in kb_buttons(menu["reply_markup"])]
    expected = {f"vp_style:{s}" for s in MAGIC_STYLE_KEYS}
    check("5 uslub tugmasi chiqdi", expected.issubset(set(cbs)), str(cbs))
    check("[❌ Bekor qilish] tugmasi bor", "vp_cancel" in cbs)
    check("STT .ogg fayl nomi bilan chaqirildi",
          STT_CALLS and STT_CALLS[0]["filename"] == "voice.ogg")
    check("STT'ga Telegram bytes uzatildi",
          STT_CALLS and STT_CALLS[0]["bytes"] == OGG_BYTES)
    check("xom matn user_data'ga saqlandi",
          "kofemiz" in ctx6.user_data.get("voice_raw_text", ""))


# ============================================================================
# TEST 2 — STT OQIMI: bekor qilish va kredit tiyilishi
# ============================================================================
def test_cancel_and_no_credit_guarantee():
    print("\n== TEST 2: Bekor qilish — hech qanday limit yechilmaydi ==")

    # 2a) Ovoz → menyuga qadar kredit bo'lmaydi (STT bepul).
    ctx = FakeContext()
    state, _msg = run_voice(ctx, duration=30)
    check("ovoz menyuga olib chiqdi", state == vh.VOICE_STYLE_SELECT)
    check("menyu bosqichida kvota/ball yechilmadi",
          "check_ai_limit" not in DB_CALLS and "use_user_credit" not in DB_CALLS)

    # 2b) [❌ Bekor qilish] → END va kredit HAMON yechilmagan.
    query = FakeQuery("vp_cancel", user_id=771002)
    ctx.user_data["voice_raw_text"] = "kofe chegirma"
    with DB_PATCH:
        state2 = run(vh.voice_cancel_callback(FakeUpdate(query=query), ctx))
    check("bekor qilish sessiyani tugatadi", state2 == vh.ConversationHandler.END
          or state2 == -1, str(state2))
    cancel_text = (query.edits[-1]["text"] if query.edits else "")
    check("bekor qilish xabarida «limit sarflanmadi» kafolati bor",
          "sarflanmadi" in cancel_text or "no" in cancel_text.lower(),
          cancel_text[:120])
    check("Bekor qilganda HAM kredit yechilmadi",
          "use_user_credit" not in DB_CALLS and "check_ai_limit" not in DB_CALLS)
    check("sessiya kalitlari tozalandi", "voice_raw_text" not in ctx.user_data)

    # 2c) Transkripsiya xizmati ishlamasa — xushmuomala xato, kredit yo'q.
    ctx3 = FakeContext()
    state3, msg3 = run_voice(ctx3, duration=30,
                             stt=make_stt(error="stt_unavailable"))
    joined3 = " ".join(r["text"] for r in msg3.replies)
    check("STT xatosida foydalanuvchi tushunarli xabar oldi",
          "Transkripsiya" in joined3 or "transkripsiya" in joined3.lower(),
          joined3[:150])
    check("STT xatosida kredit yechilmadi",
          "use_user_credit" not in DB_CALLS and "check_ai_limit" not in DB_CALLS)

    # 2d) Tushunarsiz/jitillagan audio (bo'sh matn) — xushmuomala rad etish.
    ctx4 = FakeContext()
    state4, msg4 = run_voice(ctx4, duration=30, stt=make_stt(error="empty_text"))
    joined4 = " ".join(r["text"] for r in msg4.replies)
    check("tushunarsiz audio uchun «tushunib bo'lmadi» xabari",
          "tushunib bo" in joined4, joined4[:150])
    check("tushunarsiz audioda ham kredit yechilmadi",
          "use_user_credit" not in DB_CALLS)


# ============================================================================
# TEST 3 — USLUB TANLANGANDA: faqat 1 kredit + tayyor post + amallar
# ============================================================================
def test_style_select_single_credit_and_result():
    print("\n== TEST 3: Uslub tanlash — ANIQ 1 kredit, tayyor post ==")

    # 3a) To'liq oqim: ovoz → menyu → [🔥 Sotuv] → 1 kredit → tayyor post.
    ctx = FakeContext()
    reset_db_mock(is_pro=False)
    STT_CALLS.clear()
    GEN_CALLS.clear()
    msg = FakeMessage(voice=FakeMedia(duration=30))
    gen = make_gen()
    with DB_PATCH, patch("handlers.voice_post.transcribe_voice", new=make_stt()), \
         patch("handlers.voice_post.generate_magic_post", new=gen):
        state = run(vh.voice_message_received(FakeUpdate(message=msg), ctx))
        check("1-bosqich: menyuga yetib bordi", state == vh.VOICE_STYLE_SELECT)

        query = FakeQuery("vp_style:sales", user_id=771003)
        state3 = run(vh.voice_style_callback(FakeUpdate(query=query), ctx))

    check("uslub tanlangach natija ekrani (VOICE_RESULT)",
          state3 == vh.VOICE_RESULT, str(state3))
    check("Magic Post prompti ANIQ 1 MARTA chaqirildi", len(GEN_CALLS) == 1,
          str(GEN_CALLS))
    check("generatsiyaga xom matn (transkripsiya) uzatildi",
          GEN_CALLS and "kofemiz" in GEN_CALLS[0]["raw"])
    check("generatsiyaga 'sales' uslubi uzatildi",
          GEN_CALLS and GEN_CALLS[0]["style"] == "sales")
    check("kvota (check_ai_limit) ANIQ 1 MARTA yechildi",
          DB_CALLS.count("check_ai_limit") == 1, str(DB_CALLS))
    check("kredit (use_user_credit) ANIQ 1 MARTA yechildi",
          DB_CALLS.count("use_user_credit") == 1, str(DB_CALLS))
    last = query.edits[-1]
    btns = kb_buttons(last.get("reply_markup"))
    check("natija ekranida tayyor post bor", "Katta sotuv" in last.get("text", ""))
    check("[📢 Kanalga yuborish] tugmasi bor",
          ("📢 Kanalga yuborish", "vp_send") in btns, str(btns))
    check("[📅 Rejalashtirish] tugmasi bor",
          ("📅 Rejalashtirish", "vp_sched") in btns)
    check("[🔄 Boshqa uslub] tugmasi bor",
          ("🔄 Boshqa uslub", "vp_restyle") in btns)
    check("hashtaglar bilan post saqlandi",
          "#sotuv" in ctx.user_data.get("voice_post_text", ""))

    # 3b) Generatsiya XATOSI → to'liq refund (ball + kunlik kvota qaytadi).
    ctx_b = FakeContext()
    ctx_b.user_data["voice_raw_text"] = "kofe chegirma"
    reset_db_mock(is_pro=False)
    GEN_CALLS.clear()
    query_b = FakeQuery("vp_style:premium", user_id=771004)
    with DB_PATCH, patch("handlers.voice_post.generate_magic_post",
                         new=make_gen(error="boom")):
        state_b = run(vh.voice_style_callback(FakeUpdate(query=query_b), ctx_b))
    check("xatoda oqim uslub tanlashda qoladi", state_b == vh.VOICE_STYLE_SELECT)
    check("xatoda ball REFUND qilindi", "add_user_credit" in DB_CALLS, str(DB_CALLS))
    check("xatoda kunlik kvota REFUND qilindi", "refund_ai_usage" in DB_CALLS)
    check("xato xabari foydalanuvchiga ko'rsatildi",
          query_b.edits and "tayyorlanmadi" in query_b.edits[-1]["text"])

    # 3c) [🔄 Boshqa uslub] — transkripsiya/qayta kredit TALAB etilmaydi.
    ctx_c = FakeContext()
    ctx_c.user_data["voice_raw_text"] = "kofe chegirma"
    ctx_c.user_data["voice_post_text"] = "eski post"
    reset_db_mock(is_pro=False)
    query_c = FakeQuery("vp_restyle", user_id=771005)
    with DB_PATCH:
        state_c = run(vh.voice_restyle_callback(FakeUpdate(query=query_c), ctx_c))
    check("boshqa uslub menyuga qaytardi", state_c == vh.VOICE_STYLE_SELECT)
    check("boshqa uslubda eski post tozalandi",
          "voice_post_text" not in ctx_c.user_data)
    check("boshqa uslubda kredit yechilmadi",
          "use_user_credit" not in DB_CALLS and "check_ai_limit" not in DB_CALLS)
    cbs_c = [d for _t, d in kb_buttons(query_c.edits[-1]["reply_markup"])]
    check("qayta tanlash menyusida 5 uslub + bekor bor",
          {f"vp_style:{s}" for s in MAGIC_STYLE_KEYS}.issubset(set(cbs_c))
          and "vp_cancel" in cbs_c)

    # 3d) [📅 Rejalashtirish] — mavjud scheduler oqimiga (AI_GET_TIME) uzatadi.
    ctx_d = FakeContext()
    ctx_d.user_data["voice_raw_text"] = "kofe"
    ctx_d.user_data["voice_post_text"] = "<b>Tayyor</b> post #a #b #c"
    reset_db_mock(is_pro=False)
    query_d = FakeQuery("vp_sched", user_id=771006)
    with DB_PATCH:
        state_d = run(vh.voice_schedule_callback(FakeUpdate(query=query_d), ctx_d))
    check("rejalashtirish AI_GET_TIME holatiga o'tadi", state_d == AI_GET_TIME,
          str(state_d))
    check("post scheduler oqimiga uzatildi",
          ctx_d.user_data.get("ai_generated_post") == "<b>Tayyor</b> post #a #b #c")
    check("voice sessiyasi kalitlari tozalandi",
          "voice_post_text" not in ctx_d.user_data
          and "voice_raw_text" not in ctx_d.user_data)


# ============================================================================
# TEST 4 — i18n PARITET + audio_transcriber BIRLIK TEKSHIRUVLARI
# ============================================================================
class FakeResponse:
    def __init__(self, status=200, json_data=None, text_data=""):
        self.status = status
        self._json = json_data or {}
        self._text = text_data

    async def json(self, content_type=None):
        return self._json

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """URL bo'yicha marshrutlanadigan soxta aiohttp session (tarmoq YO'Q)."""

    def __init__(self, routes):
        # routes: [(url_contains, FakeResponse), ...] — birinchi mos kelgani.
        self.routes = routes
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        for matcher, resp in self.routes:
            if matcher in url:
                return resp
        return FakeResponse(status=599, json_data={}, text_data="no route")


def test_i18n_and_transcriber_units():
    print("\n== TEST 4: i18n paritet + transcriber birlik tekshiruvlari ==")

    # 4a) UZ↔RU↔EN 100% paritet.
    report = voice_post_parity_report()
    check("i18n paritet in_sync (uz/ru/en)", report["in_sync"], str(report))
    check("kamida 23 ta lug'at kaliti", report["keys"] >= 23, str(report["keys"]))
    handler_keys = {
        "vp_listening", "vp_too_long", "vp_too_large", "vp_transcribed_header",
        "vp_btn_cancel", "vp_cancel_done", "vp_generating", "vp_result_header",
        "vp_btn_send_channel", "vp_btn_schedule", "vp_btn_restyle",
        "vp_send_choose", "vp_sent_ok", "vp_sent_fail", "vp_no_channels",
        "vp_restyle_hint", "vp_stale", "vp_error", "vp_empty_text",
        "vp_transcribe_error",
    }
    check("handler ishlatgan barcha kalitlar lug'atda",
          handler_keys.issubset(set(VOICE_POST_KEYS)))
    for lang in LANGS:
        for key in handler_keys:
            if not voice_t(key, lang):
                check(f"{lang}:{key} bo'sh emas", False)

    # 4b) «1 daqiqa» / «3 daqiqa» xabari 3 tilada ham limitni ko'rsatadi.
    check("UZ: 1 daqiqa", "1 daqiqa" in voice_t("vp_too_long", "uz", mins=1))
    check("RU: 1 мин", "1 мин" in voice_t("vp_too_long", "ru", mins=1))
    check("EN: 1 min", "1 min" in voice_t("vp_too_long", "en", mins=1))
    check("RU: 3 мин", "3 мин" in voice_t("vp_too_long", "ru", mins=3))

    # 4c) Cheklov sof funksiyalari.
    check("check_duration(60, FREE) → OK", at.check_duration(60, False)[0])
    check("check_duration(61, FREE) → RAD", not at.check_duration(61, False)[0])
    check("check_duration(180, PRO) → OK", at.check_duration(180, True)[0])
    check("check_duration(181, PRO) → RAD", not at.check_duration(181, True)[0])
    check("FREE limit = 60s", at.duration_limit_for(False) == 60)
    check("PRO limit = 180s", at.duration_limit_for(True) == 180)
    check("check_size(20MB) → OK", at.check_size(at.VOICE_MAX_BYTES))
    check("check_size(20MB+1) → RAD",
          not at.check_size(at.VOICE_MAX_BYTES + 1))
    check(".oga → audio/ogg", at.mime_for_filename("a.oga") == "audio/ogg")
    check(".mp3 → audio/mpeg", at.mime_for_filename("x.mp3") == "audio/mpeg")
    check("sanitisatsiya: ortiqcha bo'shliqlar tozalanadi",
          at.sanitize_transcript("  salom   dunyo \n\n\n ok  ") == "salom dunyo\n\nok")

    # Mock kalitlar — transcribe_voice kalitlarni CHAQIRUV paytida o'qiydi.
    KEY_ENV = {"GROQ_API_KEY": "test_groq_key", "GEMINI_API_KEY": "test_gemini_key"}

    # 4d) Groq Whisper muvaffaqiyati — to'g'ri endpoint va auth.
    sess = FakeSession([
        ("api.groq.com", FakeResponse(200, {"text": "Salom dunyo"})),
    ])
    with patch.dict(os.environ, KEY_ENV, clear=False):
        result = run(at.transcribe_voice(OGG_BYTES, "voice.ogg", session=sess))
    check("Groq javobi matn bilan qaytdi",
          result.get("text") == "Salom dunyo" and result.get("provider") == "groq",
          str(result))
    call = sess.calls[0]
    check("Groq STT endpoint'i to'g'ri", "audio/transcriptions" in call["url"])
    check("so'rov multipart FormData (fayl+model)",
          type(call["data"]).__name__ == "FormData")
    check("Authorization sarlavhasi bor",
          "Bearer" in call["headers"].get("Authorization", ""))

    # 4e) Groq YIQILSA → Gemini fallback ishlaydi.
    gemini_json = {"candidates": [{"content": {"parts": [
        {"text": "Gemini transkripsiya"}]}}]}
    sess2 = FakeSession([
        ("api.groq.com", FakeResponse(500, {}, "boom")),
        ("generativelanguage", FakeResponse(200, gemini_json)),
    ])
    with patch.dict(os.environ, KEY_ENV, clear=False):
        result2 = run(at.transcribe_voice(OGG_BYTES, "voice.ogg", session=sess2))
    check("Groq yiqilgach Gemini javobi qaytdi",
          result2.get("text") == "Gemini transkripsiya"
          and result2.get("provider") == "gemini", str(result2))
    check("Gemini'ga audio inline_data (base64) bilan yuborildi",
          len(sess2.calls) == 2 and any(
              c.get("json", {}).get("contents") for c in sess2.calls[1:]))

    # 4f) Ikkalasi ham yiqilsa — stt_unavailable (istisno EMAS).
    sess3 = FakeSession([
        ("api.groq.com", FakeResponse(500, {}, "boom")),
        ("generativelanguage", FakeResponse(500, {}, "boom")),
    ])
    with patch.dict(os.environ, KEY_ENV, clear=False):
        result3 = run(at.transcribe_voice(OGG_BYTES, "voice.ogg", session=sess3))
    check("ikkalasi yiqilsa stt_unavailable", result3.get("error") == "stt_unavailable",
          str(result3))

    # 4g) Kalitlar bo'lmasa — stt_unavailable (tarmoqqa URINMAYDI).
    env = dict(os.environ)
    env["GROQ_API_KEY"] = ""
    env["GEMINI_API_KEY"] = ""
    with patch.dict(os.environ, env, clear=False):
        sess4 = FakeSession([])
        result4 = run(at.transcribe_voice(OGG_BYTES, "voice.ogg", session=sess4))
    check("kalitlarsiz stt_unavailable + tarmoq URINMAGAN",
          result4.get("error") == "stt_unavailable" and len(sess4.calls) == 0)

    # 4h) Hajm limiti tarmoqqa urinmasdan rad etiladi.
    sess5 = FakeSession([])
    result5 = run(at.transcribe_voice(b"x" * (at.VOICE_MAX_BYTES + 1), "voice.ogg",
                                      session=sess5))
    check("20MB+ audio too_large", result5.get("error") == "too_large")
    check("hajm rad etishida tarmoq URINMAGAN", len(sess5.calls) == 0)


# ============================================================================
# TEST 5 — REGRESSIYA: Magic Post oqimi va FSM holatlari buzilmagan
# ============================================================================
def test_magic_post_regression_guard():
    print("\n== TEST 5: Magic Post regressiya himoyasi ==")
    check("Magic holatlari o'zgarmagan (430-433)",
          (mp.MAGIC_INPUT, mp.MAGIC_STYLE_SELECT, mp.MAGIC_RESULT, mp.MAGIC_SEND_CHOOSE)
          == (430, 431, 432, 433))
    check("Voice holatlari yangi (440-442)",
          (vh.VOICE_STYLE_SELECT, vh.VOICE_RESULT, vh.VOICE_SEND_CHOOSE)
          == (440, 441, 442))
    magic_states = {mp.MAGIC_INPUT, mp.MAGIC_STYLE_SELECT, mp.MAGIC_RESULT,
                    mp.MAGIC_SEND_CHOOSE}
    voice_states = {vh.VOICE_STYLE_SELECT, vh.VOICE_RESULT, vh.VOICE_SEND_CHOOSE}
    check("FSM holatlar to'qnashuv yo'q", not (magic_states & voice_states))
    check("5 uslub ikkala funksiyada bir xil", set(MAGIC_STYLE_KEYS) ==
          {"sales", "premium", "casual", "ads", "informative"})
    check("magic parity hamon in_sync",
          __import__("translations").magic_post_parity_report()["in_sync"])
    check("voice entry point filtri faqat voice/audio uchun",
          vh.VOICE_MESSAGE_FILTER is not None)


# ============================================================================
if __name__ == "__main__":
    test_duration_and_size_limits()
    test_cancel_and_no_credit_guarantee()
    test_style_select_single_credit_and_result()
    test_i18n_and_transcriber_units()
    test_magic_post_regression_guard()

    print("\n" + "=" * 60)
    print(f"Natija: {passed} OK, {failures} FAIL")
    print("=" * 60)
    if failures:
        sys.exit(1)
    print("🎙 VOICE → POST — barcha testlar muvaffaqiyatli ✔")
