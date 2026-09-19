#!/usr/bin/env python3
"""📸 IMAGE → POST — 3-BOSQICH: VISION FALLBACK va CAPTION-EXTRACTION testlari.

Tashqi Telegram/Gemini/Neon xizmatlari mock qilingan (offline). Qamrov:

  1. Vision model zanjiri: retired ``gemini-1.5-flash`` ishlatilmaydi, 404/429/
     5xx/timeout'da navbatdagi model sinaladi, hammasi yiqilsa RECOVERABLE
     ``VisionUnavailableError`` ko'tariladi;
  2. Caption bilan kelgan rasm + Vision xatosi → foydalanuvchiga QURUQ XATO
     CHIQMAYDI: caption asosida tahlil tuziladi va uslub menyusi chiqadi;
  3. Caption'siz rasm + Vision xatosi → muloyim "mavzu yozing" so'rovi va
     ``IMAGE_TOPIC_INPUT`` holati; mavzu yozilgach uslub menyusi;
  4. Forward qilingan / ``text`` maydonli xabar captioni ham olinadi;
  5. Format/hajm xatosi (rasmning o'zi yaroqsiz) hali ham yangi rasm so'raydi;
  6. Matn asosidagi tahlil → ``generate_image_post`` Magic Post generatoriga
     uzatadi (Vision prompt emas), uslub mapping to'g'ri;
  7. Natija klaviaturasi Magic Post bilan bir xil ixcham layout:
     [📢 Kanalga yuborish] [📅 Rejalashtirish] / [✏️ Qayta yozish]
     [📊 Baholash] / [◀️ Orqaga] — eski callback'lar saqlangan;
  8. i18n: yangi kalitlar UZ/RU/EN da mavjud, umumiy paritet buzilmagan;
  9. FSM: IMAGE_TOPIC_INPUT (525) noyob va handlers'da ro'yxatdan o'tgan.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:IMAGE_FALLBACK_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

passed = 0
failures = 0
LANGS = ("uz", "ru", "en")


def check(name, condition, extra=""):
    global passed, failures
    if condition:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


def run(coro):
    return asyncio.run(coro)


# ----------------------------------------------------------------------------
# Fake Telegram / aiohttp obyektlari
# ----------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.payload = payload or {}
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return self.payload


class ScriptedSession:
    """Har bir chaqiruv uchun oldindan belgilangan javob (status yoki exception)."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append(url)
        item = self.script.pop(0) if self.script else 503
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, int):
            return FakeResponse(status=item)
        return FakeResponse(payload=item)


def good_payload(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


class FakeFile:
    def __init__(self, data):
        self.data = data

    async def download_as_bytearray(self):
        return bytearray(self.data)


class FakeBot:
    def __init__(self, data):
        self.data = data

    async def get_file(self, file_id):
        return FakeFile(self.data)


class FakeMessage:
    def __init__(self, photo=None, caption="", text=None, forward=False):
        self.photo = photo or []
        self.document = None
        self.caption = caption
        self.text = text
        self.replies = []
        if forward:
            self.forward_origin = SimpleNamespace(type="channel")
            self.forward_date = 1

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kwargs):
        self.replies.append({"kind": "text", "text": text, "reply_markup": reply_markup})

    async def reply_photo(self, photo=None, caption=None, reply_markup=None, parse_mode=None, **kwargs):
        self.replies.append({"kind": "photo", "photo": photo, "caption": caption, "reply_markup": reply_markup})


class FakeQuery:
    def __init__(self, data, message, user_id=777):
        self.data = data
        self.message = message
        self.from_user = SimpleNamespace(id=user_id)
        self.edits = []

    async def answer(self, *a, **k):
        return None

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None, **k):
        self.edits.append({"text": text, "reply_markup": reply_markup})

    async def edit_message_reply_markup(self, reply_markup=None, **k):
        self.edits.append({"markup_only": True})


class FakeUpdate:
    def __init__(self, message=None, query=None, user_id=777):
        self.message = message
        self.callback_query = query
        self.effective_user = SimpleNamespace(id=user_id)
        self.effective_chat = SimpleNamespace(id=user_id, type="private")


class FakeContext:
    def __init__(self, bot):
        self.bot = bot
        self.user_data = {"lang": "uz"}
        self.chat_data = {}
        self.bot_data = {}


def buttons(markup):
    return [
        (b.text, b.callback_data)
        for row in (getattr(markup, "inline_keyboard", None) or [])
        for b in row
    ]


JPEG = b"\xff\xd8\xff" + b"mock-jpeg-bytes"
PHOTO = SimpleNamespace(file_id="photo-42", file_size=len(JPEG), mime_type="image/jpeg")


# ----------------------------------------------------------------------------
def test_vision_model_chain_and_retry():
    print("== TEST 1: Vision model zanjiri (retired yo'q, 404/429/timeout → keyingi model) ==")
    from utils import vision_analyzer as va

    chain = va.vision_model_chain()
    check("zanjir bo'sh emas", bool(chain), str(chain))
    check("retired gemini-1.5-* zanjirda YO'Q", not any("1.5" in m for m in chain), str(chain))
    check("zanjirda dublikat yo'q", len(chain) == len(set(chain)), str(chain))
    check("admin bergan model birinchi", va.vision_model_chain("gemini-2.5-pro")[0] == "gemini-2.5-pro")
    check("retired admin modeli tashlab yuboriladi",
          "gemini-1.5-flash" not in va.vision_model_chain("gemini-1.5-flash"))

    # 404 → 429 → OK : uchinchi modelda javob keladi
    session = ScriptedSession([404, 429, good_payload(
        '{"product_name":"Kalendar","category":"Poligrafiya","summary":"2026 kalendar"}'
    )])
    result = run(va.analyze_image(JPEG, api_key="k", session=session))
    check("404/429 dan keyin navbatdagi model sinaldi", len(session.calls) == 3, str(session.calls))
    check("3-modelda natija qaytdi", result.get("product_name") == "Kalendar", str(result))
    check("natijada ishlatilgan model qayd etildi", result.get("model") == chain[2], str(result.get("model")))

    # Timeout → bo'sh javob → tushunarsiz javob → 500 → barchasi yiqildi
    session = ScriptedSession([asyncio.TimeoutError(), good_payload(""), good_payload("not json"), 500, 503, 503])
    try:
        run(va.analyze_image(JPEG, api_key="k", session=session))
    except va.VisionError as exc:
        check("barcha modellar yiqilsa VisionError", True)
        check("… va u RECOVERABLE (fallback uchun)", getattr(exc, "recoverable", False) is True)
        check("… VisionUnavailableError turi", isinstance(exc, va.VisionUnavailableError))
    else:
        check("barcha modellar yiqilsa VisionError", False)

    # API key yo'q → recoverable
    try:
        run(va.analyze_image(JPEG, api_key="", session=ScriptedSession([])))
    except va.VisionError as exc:
        check("API kalitsiz xato ham recoverable", getattr(exc, "recoverable", False) is True)
    else:
        check("API kalitsiz xato ham recoverable", False)

    # Format xatosi → NON-recoverable
    try:
        va.validate_image(b"<html>not image</html>")
    except va.VisionError as exc:
        check("format xatosi recoverable EMAS", getattr(exc, "recoverable", False) is False)
    else:
        check("format xatosi recoverable EMAS", False)


def test_analysis_from_text():
    print("== TEST 2: caption/mavzudan tahlil sxemasi ==")
    from utils import vision_analyzer as va

    caption = "Qon bosimi jadvali\nNarxi: 45 000 so'm\nYetkazib berish: bepul"
    a = va.analysis_from_text(caption, va.TEXT_SOURCE_CAPTION)
    check("source=caption", a.get("source") == "caption", str(a))
    check("source_text saqlangan", a.get("source_text", "").startswith("Qon bosimi"), str(a))
    check("product_name birinchi qatordan", a.get("product_name") == "Qon bosimi jadvali", str(a))
    check("caption_details price ajratildi", "45" in str(a.get("caption_details", {}).get("price", "")), str(a))
    check("caption_details delivery ajratildi", "bepul" in str(a.get("caption_details", {}).get("delivery", "")), str(a))
    check("is_text_based_analysis True", va.is_text_based_analysis(a))
    check("oddiy vision tahlili text-based EMAS",
          not va.is_text_based_analysis(va.normalize_analysis({"product_name": "Sumka"})))
    t = va.analysis_from_text("Yangi kolleksiya", va.TEXT_SOURCE_TOPIC)
    check("topic source", t.get("source") == "topic")
    check("noma'lum source caption'ga tushadi", va.analysis_from_text("x", "hacker")["source"] == "caption")


def _patch_handler(ip, analyzer, generator=None, db_runner=None):
    orig = (ip.analyze_image, ip.generate_image_post, ip.db.run_db)
    ip.analyze_image = analyzer
    if generator is not None:
        ip.generate_image_post = generator
    if db_runner is not None:
        ip.db.run_db = db_runner
    return orig


def _restore_handler(ip, orig):
    ip.analyze_image, ip.generate_image_post, ip.db.run_db = orig


async def failing_vision(data, caption="", **kwargs):
    from utils.vision_analyzer import VisionUnavailableError
    raise VisionUnavailableError("⏳ Vision xizmati band.")


async def exploding_vision(data, caption="", **kwargs):
    raise RuntimeError("model tushunmadi")


async def fake_db(func, *args, **kwargs):
    name = getattr(func, "__name__", str(func))
    if name == "is_premium":
        return False
    if name == "check_ai_limit":
        return (True, 1, 5)
    if name in ("use_user_credit", "add_user_credit", "refund_ai_usage"):
        return True
    if name == "get_user_channels":
        return [("-1001", "Demo kanal")]
    return None


def test_caption_fallback_flow():
    print("== TEST 3: caption bor + Vision xato → quruq xato YO'Q, caption asosida uslub menyusi ==")
    from handlers import image_post as ip

    caption = "Qon bosimi me'yorlari jadvali: 120/80 — normal, 140/90 — yuqori"
    for lang in LANGS:
        for vision in (failing_vision, exploding_vision):
            ctx = FakeContext(FakeBot(JPEG))
            ctx.user_data["lang"] = lang
            msg = FakeMessage(photo=[PHOTO], caption=caption)
            orig = _patch_handler(ip, vision, db_runner=fake_db)
            try:
                state = run(ip.image_photo_received(FakeUpdate(message=msg), ctx))
            finally:
                _restore_handler(ip, orig)
            label = f"[{lang}/{vision.__name__}]"
            check(f"{label} holat → IMAGE_STYLE_SELECT (jarayon to'xtamadi)",
                  state == ip.IMAGE_STYLE_SELECT, str(state))
            last = msg.replies[-1]
            check(f"{label} quruq 'tahlil qilib bo'lmadi' xatosi chiqmadi",
                  "tahlil qilib bo'lmadi" not in last["text"]
                  and "Не удалось проанализировать" not in last["text"], last["text"])
            check(f"{label} caption matni xulosada ko'rsatildi", "120/80" in last["text"], last["text"])
            cbs = [d for _t, d in buttons(last["reply_markup"])]
            check(f"{label} 5 uslub + bekor tugmalari",
                  sum(c.startswith(ip.IMAGE_STYLE_PREFIX) for c in cbs) == 5 and ip.IMAGE_CANCEL in cbs, str(cbs))
            analysis = ctx.user_data.get("image_post_analysis") or {}
            check(f"{label} tahlil caption asosida (source=caption)", analysis.get("source") == "caption", str(analysis))
            check(f"{label} file_id saqlandi (post rasm bilan chiqadi)",
                  ctx.user_data.get("image_post_file_id") == "photo-42")
            check(f"{label} caption saqlandi", ctx.user_data.get("image_post_caption") == caption)

    # Vision dict ichida error qaytarsa ham fallback
    async def error_dict_vision(data, caption="", **kwargs):
        return {"error": "model_failed"}

    ctx = FakeContext(FakeBot(JPEG))
    msg = FakeMessage(photo=[PHOTO], caption="Aksiya: 20% chegirma")
    orig = _patch_handler(ip, error_dict_vision, db_runner=fake_db)
    try:
        state = run(ip.image_photo_received(FakeUpdate(message=msg), ctx))
    finally:
        _restore_handler(ip, orig)
    check("Vision {'error':…} qaytarsa ham caption fallback", state == ip.IMAGE_STYLE_SELECT, str(state))


def test_topic_fallback_flow():
    print("== TEST 4: caption YO'Q + Vision xato → mavzu so'raladi → IMAGE_TOPIC_INPUT ==")
    from handlers import image_post as ip
    from locales.translations import safe_t

    for lang in LANGS:
        ctx = FakeContext(FakeBot(JPEG))
        ctx.user_data["lang"] = lang
        msg = FakeMessage(photo=[PHOTO], caption="")
        orig = _patch_handler(ip, failing_vision, db_runner=fake_db)
        try:
            state = run(ip.image_photo_received(FakeUpdate(message=msg), ctx))
        finally:
            _restore_handler(ip, orig)
        check(f"[{lang}] holat → IMAGE_TOPIC_INPUT", state == ip.IMAGE_TOPIC_INPUT, str(state))
        check(f"[{lang}] muloyim mavzu so'rovi",
              msg.replies[-1]["text"] == safe_t("image_topic_prompt", lang), msg.replies[-1]["text"])
        if lang == "uz":
            check("UZ matni aynan talab qilingandek",
                  msg.replies[-1]["text"].startswith("🖼 Rasm qabul qilindi! Ushbu post qaysi mavzuda"),
                  msg.replies[-1]["text"])
        check(f"[{lang}] file_id saqlanib qoldi", ctx.user_data.get("image_post_file_id") == "photo-42")

        # bo'sh mavzu → yana so'raladi
        empty = FakeMessage(text="   ")
        state = run(ip.image_topic_received(FakeUpdate(message=empty), ctx))
        check(f"[{lang}] bo'sh mavzu → yana IMAGE_TOPIC_INPUT", state == ip.IMAGE_TOPIC_INPUT, str(state))

        # mavzu yozildi → uslub menyusi
        topic_msg = FakeMessage(text="Sentyabr oyi uchun tadbirlar kalendari")
        state = run(ip.image_topic_received(FakeUpdate(message=topic_msg), ctx))
        check(f"[{lang}] mavzudan keyin IMAGE_STYLE_SELECT", state == ip.IMAGE_STYLE_SELECT, str(state))
        analysis = ctx.user_data.get("image_post_analysis") or {}
        check(f"[{lang}] tahlil source=topic", analysis.get("source") == "topic", str(analysis))
        check(f"[{lang}] mavzu xulosada ko'rindi", "kalendari" in topic_msg.replies[-1]["text"])
        cbs = [d for _t, d in buttons(topic_msg.replies[-1]["reply_markup"])]
        check(f"[{lang}] uslub tugmalari chiqdi", sum(c.startswith(ip.IMAGE_STYLE_PREFIX) for c in cbs) == 5)

    # Sessiya yo'q (file_id yo'q) → xavfsiz END
    ctx = FakeContext(FakeBot(JPEG))
    state = run(ip.image_topic_received(FakeUpdate(message=FakeMessage(text="mavzu")), ctx))
    check("file_id'siz mavzu → sessiya tugadi (crash yo'q)", state == ip.ConversationHandler.END, str(state))


def test_forwarded_and_text_caption_extraction():
    print("== TEST 5: forward qilingan / text maydonli rasm captioni ==")
    from handlers import image_post as ip

    fwd = FakeMessage(photo=[PHOTO], caption="Forward: 2026 yil kalendari", forward=True)
    check("forward caption olinadi", ip._message_caption(fwd) == "Forward: 2026 yil kalendari")
    only_text = FakeMessage(photo=[PHOTO], caption="", text="Text maydonida izoh")
    check("caption bo'sh bo'lsa text maydoni olinadi", ip._message_caption(only_text) == "Text maydonida izoh")
    check("ikkalasi bo'sh → ''", ip._message_caption(FakeMessage(photo=[PHOTO])) == "")
    check("caption 1000 belgiga qisqartiriladi", len(ip._message_caption(FakeMessage(caption="x" * 5000))) == 1000)

    ctx = FakeContext(FakeBot(JPEG))
    orig = _patch_handler(ip, failing_vision, db_runner=fake_db)
    try:
        state = run(ip.image_photo_received(FakeUpdate(message=fwd), ctx))
    finally:
        _restore_handler(ip, orig)
    check("forward rasm + Vision xato → caption fallback (STYLE_SELECT)",
          state == ip.IMAGE_STYLE_SELECT, str(state))


def test_non_recoverable_errors_still_ask_new_image():
    print("== TEST 6: rasmning o'zi yaroqsiz bo'lsa — yangi rasm so'raladi ==")
    from handlers import image_post as ip

    ctx = FakeContext(FakeBot(b"<html>not an image</html>"))
    msg = FakeMessage(photo=[PHOTO], caption="caption bor")
    orig = _patch_handler(ip, failing_vision, db_runner=fake_db)
    try:
        state = run(ip.image_photo_received(FakeUpdate(message=msg), ctx))
    finally:
        _restore_handler(ip, orig)
    check("format xatosi → IMAGE_POST_INPUT (yangi rasm)", state == ip.IMAGE_POST_INPUT, str(state))
    check("format xabari ko'rsatildi", msg.replies[-1]["text"].startswith("🖼"), msg.replies[-1]["text"])

    big = SimpleNamespace(file_id="big", file_size=11 * 1024 * 1024, mime_type="image/jpeg")
    ctx = FakeContext(FakeBot(JPEG))
    msg = FakeMessage(photo=[big], caption="")
    orig = _patch_handler(ip, failing_vision, db_runner=fake_db)
    try:
        state = run(ip.image_photo_received(FakeUpdate(message=msg), ctx))
    finally:
        _restore_handler(ip, orig)
    check("10 MB dan katta → IMAGE_POST_INPUT", state == ip.IMAGE_POST_INPUT, str(state))
    check("hajm xabari ko'rsatildi", msg.replies[-1]["text"].startswith("📦"), msg.replies[-1]["text"])

    # Rasm bo'lmagan xabar
    ctx = FakeContext(FakeBot(JPEG))
    msg = FakeMessage(text="salom")
    state = run(ip.image_photo_received(FakeUpdate(message=msg), ctx))
    check("rasmsiz xabar → IMAGE_POST_INPUT", state == ip.IMAGE_POST_INPUT, str(state))


def test_text_based_generation_uses_magic_post():
    print("== TEST 7: matn asosidagi tahlil → Magic Post generatori ==")
    from services import ai_service as svc
    from utils import vision_analyzer as va
    from utils import ai_agent as aa

    calls = []

    async def fake_magic(raw_text, style, lang="uz", is_pro=False, **kw):
        calls.append({"text": raw_text, "style": style, "lang": lang})
        return {"post_text": f"<b>{raw_text[:20]}</b> — tayyor post", "style": style}

    chain_calls = []

    async def fake_chain(prompt, system, lang=None):
        chain_calls.append(prompt)
        return {"post_text": "chain post"}

    orig_magic = getattr(aa, "generate_magic_post", None)
    orig_chain = svc.run_ai_chain
    aa.generate_magic_post = fake_magic
    svc.run_ai_chain = fake_chain
    try:
        analysis = va.analysis_from_text("Qon bosimi jadvali: 120/80 normal", va.TEXT_SOURCE_CAPTION)
        res = run(svc.generate_image_post(analysis, "discount", caption="", lang="ru", is_pro=True))
        check("post_text qaytdi", "tayyor post" in res.get("post_text", ""), str(res))
        check("Magic Post generatori chaqirildi (Vision prompt emas)", len(calls) == 1 and not chain_calls)
        check("matn AYNAN caption", calls and calls[0]["text"].startswith("Qon bosimi jadvali"))
        check("uslub mapping discount→ads", calls and calls[0]["style"] == "ads", str(calls))
        check("til uzatildi", calls and calls[0]["lang"] == "ru")
        check("style natijada image uslubi bo'lib qoladi", res.get("style") == "discount")
        check("source=text_fallback belgisi", res.get("source") == "text_fallback")
        for img, magic in (("sales", "sales"), ("premium", "premium"), ("simple", "casual"),
                           ("review", "informative")):
            check(f"mapping {img}→{magic}", svc.IMAGE_TO_MAGIC_STYLE[img] == magic)

        # Magic Post yiqilsa — run_ai_chain zaxirasi
        async def broken_magic(*a, **k):
            raise RuntimeError("boom")
        aa.generate_magic_post = broken_magic
        res = run(svc.generate_image_post(analysis, "sales", lang="uz"))
        check("Magic Post yiqilsa run_ai_chain zaxirasi ishladi",
              res.get("post_text") == "chain post" and len(chain_calls) == 1, str(res))

        # Oddiy Vision tahlili — Magic Post EMAS, odatiy prompt zanjiri
        calls.clear(); chain_calls.clear()
        aa.generate_magic_post = fake_magic
        vision = va.normalize_analysis({"product_name": "Sumka", "category": "Aksessuar"})
        res = run(svc.generate_image_post(vision, "sales", lang="uz"))
        check("Vision tahlili odatiy zanjirdan o'tadi (regressiya)",
              not calls and len(chain_calls) == 1 and "VISION TAHLILI" in chain_calls[0])

        # Bo'sh matn → error (crash yo'q)
        res = run(svc.generate_text_fallback_post("", "sales"))
        check("bo'sh matn → error dict", bool(res.get("error")))
    finally:
        if orig_magic is not None:
            aa.generate_magic_post = orig_magic
        svc.run_ai_chain = orig_chain


def test_end_to_end_fallback_to_result():
    print("== TEST 8: caption fallback → uslub → 1 kredit → rasm + post + toza tugmalar ==")
    from handlers import image_post as ip

    credit_calls = []

    async def counting_db(func, *args, **kwargs):
        name = getattr(func, "__name__", str(func))
        if name == "use_user_credit":
            credit_calls.append(1)
        return await fake_db(func, *args, **kwargs)

    async def fake_generate(analysis, style, caption="", lang="uz", is_pro=False):
        assert analysis.get("source") == "caption"
        return {"post_text": "<b>Qon bosimi</b> haqida foydali post", "style": style}

    ctx = FakeContext(FakeBot(JPEG))
    msg = FakeMessage(photo=[PHOTO], caption="Qon bosimi me'yorlari jadvali")
    orig = _patch_handler(ip, failing_vision, generator=fake_generate, db_runner=counting_db)
    try:
        state = run(ip.image_photo_received(FakeUpdate(message=msg), ctx))
        check("fallback → STYLE_SELECT", state == ip.IMAGE_STYLE_SELECT)
        check("Vision/fallback bosqichida kredit 0", not credit_calls)
        q = FakeQuery(f"{ip.IMAGE_STYLE_PREFIX}simple", message=msg)
        state = run(ip.image_style_callback(FakeUpdate(query=q), ctx))
    finally:
        _restore_handler(ip, orig)
    check("uslub → IMAGE_POST_RESULT", state == ip.IMAGE_POST_RESULT, str(state))
    check("aynan 1 kredit", len(credit_calls) == 1, str(credit_calls))
    preview = next((r for r in msg.replies if r.get("kind") == "photo"), None)
    check("natija AYNAN yuborilgan rasm bilan", preview and preview["photo"] == "photo-42")
    check("caption tayyor post", preview and "Qon bosimi" in preview["caption"])
    btns = buttons(preview["reply_markup"]) if preview else []
    check("natija tugmalari to'liq", {ip.IMAGE_SEND, ip.IMAGE_SCHEDULE, ip.IMAGE_RESTYLE, ip.IMAGE_BACK,
                                      "ps_eval:image"} <= {d for _t, d in btns}, str(btns))


def test_result_keyboard_layout_and_back():
    print("== TEST 9: natija klaviaturasi = Magic Post layout + [◀️ Orqaga] ==")
    from handlers import image_post as ip
    from handlers import magic_post as mp
    from translations import magic_t, post_score_t
    from locales.translations import safe_t

    for lang in LANGS:
        kb = ip.image_action_keyboard(lang)
        rows = [[(b.text, b.callback_data) for b in row] for row in kb.inline_keyboard]
        check(f"[{lang}] 3 qator: 2 + 2 + 1", [len(r) for r in rows] == [2, 2, 1], str(rows))
        check(f"[{lang}] 1-qator: Kanalga yuborish / Rejalashtirish",
              rows[0] == [(safe_t("image_btn_send", lang), ip.IMAGE_SEND),
                          (safe_t("image_btn_schedule", lang), ip.IMAGE_SCHEDULE)], str(rows[0]))
        check(f"[{lang}] 2-qator: Qayta yozish + Baholash",
              rows[1] == [(magic_t("mp_btn_rewrite", lang), ip.IMAGE_RESTYLE),
                          (post_score_t("ps_btn_eval", lang), "ps_eval:image")], str(rows[1]))
        check(f"[{lang}] 3-qator: Orqaga", rows[2] == [(magic_t("mp_btn_back", lang), ip.IMAGE_BACK)], str(rows[2]))
        magic_rows = [[b.text for b in row] for row in mp._magic_action_keyboard(lang).inline_keyboard]
        check(f"[{lang}] Magic Post bilan yorliqlar bir xil",
              [[t for t, _ in r] for r in rows] == magic_rows, f"{rows} vs {magic_rows}")
        for _t, d in (b for r in rows for b in r):
            check(f"[{lang}] callback ≤64 bayt: {d}", len(d.encode()) <= 64)
    check("uz yorliqlari talab qilinganidek",
          [[t for t, _ in r] for r in [[(b.text, b.callback_data) for b in row]
                                       for row in ip.image_action_keyboard("uz").inline_keyboard]]
          == [["📢 Kanalga yuborish", "📅 Rejalashtirish"],
              ["✏️ Qayta yozish", "📊 Baholash"], ["◀️ Orqaga"]])

    # [◀️ Orqaga] — sessiya tozalanadi, Kontent yaratish menyusi, END
    ctx = FakeContext(FakeBot(JPEG))
    ctx.user_data.update({"image_post_text": "x", "image_post_file_id": "f", "image_post_analysis": {}})
    msg = FakeMessage()
    q = FakeQuery(ip.IMAGE_BACK, message=msg)
    state = run(ip.image_back_callback(FakeUpdate(query=q), ctx))
    check("Orqaga → END", state == ip.ConversationHandler.END, str(state))
    check("Orqaga sessiyani tozaladi", not any(k in ctx.user_data for k in ip._SESSION_KEYS))
    check("Orqaga Kontent yaratish menyusini chizdi", msg.replies and msg.replies[-1]["reply_markup"] is not None)

    # restyle: matn asosidagi tahlilda ham ishlaydi (Vision qayta chaqirilmaydi)
    ctx = FakeContext(FakeBot(JPEG))
    ctx.user_data.update({"image_post_text": "x", "image_post_analysis": {"source": "caption"}})
    q = FakeQuery(ip.IMAGE_RESTYLE, message=FakeMessage())
    state = run(ip.image_restyle_callback(FakeUpdate(query=q), ctx))
    check("Qayta yozish → STYLE_SELECT", state == ip.IMAGE_STYLE_SELECT, str(state))


def test_i18n_and_fsm_registration():
    print("== TEST 10: i18n paritet + FSM/handler ro'yxati ==")
    from locales.translations import TRANSLATIONS, translation_parity_report
    from locales.en_overlay import EN_OVERLAY
    from handlers import image_post as ip

    keys = ("image_vision_fallback_caption", "image_text_summary_caption",
            "image_text_summary_topic", "image_topic_prompt")
    for key in keys:
        check(f"UZ: {key}", key in TRANSLATIONS["uz"])
        check(f"RU: {key}", key in TRANSLATIONS["ru"])
        check(f"EN overlay: {key}", key in EN_OVERLAY)
        texts = {TRANSLATIONS[l][key] for l in LANGS}
        check(f"{key} uchala tilda har xil (tarjima qilingan)", len(texts) == 3)
    rep = translation_parity_report()
    check("umumiy UZ/RU/EN paritet buzilmagan", rep.get("all_in_sync") is True and rep.get("en_in_sync") is True, str(rep))

    check("IMAGE_TOPIC_INPUT = 525 (noyob)", ip.IMAGE_TOPIC_INPUT == 525
          and 525 not in (ip.IMAGE_POST_INPUT, ip.IMAGE_STYLE_SELECT, ip.IMAGE_POST_RESULT,
                          ip.IMAGE_SEND_CHOOSE, ip.IMAGE_SCHEDULE_INPUT))
    try:
        from handlers import magic_post as mp, voice_post as vp, post_score as ps
        others = {mp.MAGIC_INPUT, mp.MAGIC_STYLE_SELECT, mp.MAGIC_RESULT, mp.MAGIC_SEND_CHOOSE,
                  vp.VOICE_AWAIT, vp.VOICE_STYLE_SELECT, vp.VOICE_RESULT, vp.VOICE_SEND_CHOOSE,
                  ps.POST_SCORE_INPUT, ps.POST_SCORE_RESULT, ps.POST_SCORE_SEND_CHOOSE}
        check("525 boshqa killer-featura holatlari bilan to'qnashmaydi", 525 not in others)
    except Exception as exc:  # pragma: no cover
        check("boshqa modullar import bo'ldi", False, str(exc))

    src = (ROOT / "handlers" / "__init__.py").read_text(encoding="utf-8")
    check("handlers: IMAGE_TOPIC_INPUT holati ro'yxatda", "IMAGE_TOPIC_INPUT: all_menu_jumps" in src)
    check("handlers: image_topic_received ulangan", "image_topic_received" in src)
    check("handlers: image_back_callback ulangan (^image_back$)", 'pattern=r"^image_back$"' in src)
    check("handlers: stale image_* tugmalari hali ham ushlanadi", 'pattern=r"^image_|^img_"' in src)


def main():
    print("=" * 62)
    print(" 📸 IMAGE → POST — 3-BOSQICH: VISION FALLBACK + CAPTION TESTLARI")
    print("=" * 62)
    for test in (
        test_vision_model_chain_and_retry,
        test_analysis_from_text,
        test_caption_fallback_flow,
        test_topic_fallback_flow,
        test_forwarded_and_text_caption_extraction,
        test_non_recoverable_errors_still_ask_new_image,
        test_text_based_generation_uses_magic_post,
        test_end_to_end_fallback_to_result,
        test_result_keyboard_layout_and_back,
        test_i18n_and_fsm_registration,
    ):
        try:
            test()
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            check(f"{test.__name__} istisnosiz o'tdi", False, repr(exc))
        print()
    print(f"NATIJA: {passed} OK, {failures} FAIL")
    if failures:
        print("XATOLIK: image-to-post fallback testlari yiqildi ❌")
        return 1
    print("IMAGE → POST FALLBACK TESTLARI 100% YASHIL ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
