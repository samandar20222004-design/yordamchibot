#!/usr/bin/env python3
"""📸 IMAGE → POST — KILLER FEATURE #3 regression tests.

Tashqi Telegram/Gemini/Neon xizmatlari mock qilingan. Qamrov:
  1. JPEG bytes Gemini Vision'ga inline_data/base64 sifatida ketadi va
     mahsulot tahlili qaytadi;
  2. Vision tahlili/style menu bosqichida kredit yechilmaydi, style tanlanganda
     aynan bitta ``use_user_credit`` chaqiriladi, bekor qilishda esa nol;
  3. direct channel delivery va scheduler payload'i photo + caption sifatida
     tuziladi.
"""

from __future__ import annotations

import asyncio
import base64
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:IMAGE_POST_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

passed = 0
failures = 0


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


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse({
            "candidates": [{
                "content": {"parts": [{"text": (
                    '{"product_name":"Charm sumka", "category":"Aksessuar", '
                    '"visual_features":{"color":"qora", "material":"charm", '
                    '"design":"minimal", "style":"premium"}, '
                    '"caption_details":{"price":"250 000 so\'m", '
                    '"delivery":"Toshkent bo\'ylab"}, '
                    '"summary":"Qora charm sumka aniqlandi", "confidence":"high"}'
                )}]}
            }]
        })


class FakeTelegramFile:
    def __init__(self, data):
        self.data = data

    async def download_as_bytearray(self):
        return bytearray(self.data)


class FakeBot:
    def __init__(self, data):
        self.data = data
        self.get_file_calls = []
        self.photo_calls = []

    async def get_file(self, file_id):
        self.get_file_calls.append(file_id)
        return FakeTelegramFile(self.data)

    async def send_photo(self, **kwargs):
        self.photo_calls.append(kwargs)
        return SimpleNamespace(message_id=len(self.photo_calls))


class FakeMessage:
    def __init__(self, photo=None, caption="", text=None):
        self.photo = photo
        self.document = None
        self.caption = caption
        self.text = text
        self.replies = []
        self.chat_id = 777

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kwargs):
        self.replies.append({"kind": "text", "text": text, "reply_markup": reply_markup})
        return self

    async def reply_photo(self, photo=None, caption=None, reply_markup=None,
                          parse_mode=None, **kwargs):
        self.replies.append({
            "kind": "photo", "photo": photo, "caption": caption,
            "reply_markup": reply_markup,
        })
        return SimpleNamespace(message_id=len(self.replies))


class FakeQuery:
    def __init__(self, data, message=None, user_id=771000):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = message or FakeMessage()
        self.answers = []
        self.edits = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None, **kwargs):
        self.edits.append({"text": text, "reply_markup": reply_markup})


class FakeUpdate:
    def __init__(self, message=None, query=None, user_id=771000):
        self.message = message
        self.callback_query = query
        self.effective_user = SimpleNamespace(id=(query.from_user.id if query else user_id))


class FakeContext:
    def __init__(self, bot):
        self.bot = bot
        self.user_data = {"lang": "uz"}


def callbacks(markup):
    return [
        button.callback_data
        for row in (getattr(markup, "inline_keyboard", None) or [])
        for button in row
    ]


def test_image_validation_contract():
    print("== TEST 0: format safety va 10 MB limit ==")
    from utils.vision_analyzer import VisionError, MAX_IMAGE_BYTES, validate_image

    valid = b"\xff\xd8\xff" + b"jpeg"
    payload = validate_image(valid, mime_type="text/plain")
    check("haqiqiy JPEG magic bytes qabul qilindi", payload.mime_type == "image/jpeg")
    try:
        validate_image(b"not-an-image", mime_type="image/jpeg")
    except VisionError:
        check("soxta MIME/format xavfsiz rad etildi", True)
    else:
        check("soxta MIME/format xavfsiz rad etildi", False)
    try:
        validate_image(valid, max_bytes=2)
    except VisionError:
        check("maksimal hajm oshsa rad etildi", True)
    else:
        check("maksimal hajm oshsa rad etildi", False)
    check("hard limit 10 MB dan oshmaydi", MAX_IMAGE_BYTES <= 10 * 1024 * 1024)


def test_gemini_vision_analysis():
    print("== TEST 1: Gemini Vision bytes/base64 + mahsulot tahlili ==")
    from utils import vision_analyzer as va

    jpeg = b"\xff\xd8\xff" + b"mock-jpeg"
    session = FakeSession()
    result = run(va.analyze_image(
        jpeg,
        caption="Narxi 250 000 so'm, Toshkent bo'ylab yetkazib berish",
        api_key="test-key",
        session=session,
    ))
    check("Vision product_name qaytardi", result["product_name"] == "Charm sumka", str(result))
    check("Vision category qaytardi", result["category"] == "Aksessuar", str(result))
    check("Vision visual features qaytdi", result["visual_features"]["material"] == "charm")
    check("Vision caption detail qaytdi", "250" in result["caption_details"]["price"])
    check("Gemini endpoint 1.5 Flash", "gemini-1.5-flash" in session.calls[0]["url"])
    body = session.calls[0]["json"]
    parts = body["contents"][0]["parts"]
    inline = next(part["inline_data"] for part in parts if "inline_data" in part)
    check("Gemini inline_data MIME jpeg", inline["mime_type"] == "image/jpeg")
    check("Gemini inline_data base64", base64.b64decode(inline["data"]) == jpeg)
    system = body["systemInstruction"]["parts"][0]["text"]
    check("Vision prompt product/category/features qoidalarini so'raydi",
          all(word in system for word in ("product_name", "category", "visual_features", "caption_details")))


def test_style_credit_contract():
    print("== TEST 2: style tanlanganda 1 credit, cancel'da 0 ==")
    from handlers import image_post as ip

    image_bytes = b"\xff\xd8\xff" + b"image"
    bot = FakeBot(image_bytes)
    ctx = FakeContext(bot)
    photo = SimpleNamespace(file_id="photo-1", file_size=len(image_bytes), mime_type="image/jpeg")
    message = FakeMessage(photo=[photo], caption="250 000 so'm")
    update = FakeUpdate(message=message)

    async def fake_analyze(data, caption="", **kwargs):
        return {
            "product_name": "Charm sumka",
            "category": "Aksessuar",
            "visual_features": {
                "color": "qora", "material": "charm", "design": "minimal", "style": "premium",
            },
            "caption_details": {"price": "250 000 so'm"},
            "summary": "Qora charm sumka aniqlandi",
        }

    calls = []

    async def fake_db(func, *args, **kwargs):
        name = getattr(func, "__name__", str(func))
        calls.append(name)
        if name == "is_premium":
            return False
        if name == "check_ai_limit":
            return (True, 1, 5)
        if name == "use_user_credit":
            return True
        if name == "get_user_channels":
            return [("-1001", "Demo kanal")]
        if name in ("add_user_credit", "refund_ai_usage"):
            return True
        return None

    async def fake_generate(analysis, style, caption="", lang="uz", is_pro=False):
        return {"post_text": "<b>Sumka uchun ajoyib taklif!</b>\n#sumka #aksiya", "style": style}

    original_analyze = ip.analyze_image
    original_generate = ip.generate_image_post
    original_run_db = ip.db.run_db
    ip.analyze_image = fake_analyze
    ip.generate_image_post = fake_generate
    ip.db.run_db = fake_db
    try:
        state = run(ip.image_photo_received(update, ctx))
        check("Vision tahlilidan keyin style state", state == ip.IMAGE_STYLE_SELECT, str(state))
        check("style menu 5 uslub + cancel", sum(cb.startswith(ip.IMAGE_STYLE_PREFIX) for cb in callbacks(message.replies[-1]["reply_markup"])) == 5)
        check("Vision bosqichida kredit yechilmagan", "use_user_credit" not in calls)

        # Bekor qilish — use_user_credit hali ham 0.
        cancel_query = FakeQuery(ip.IMAGE_CANCEL, message=message)
        cancel_state = run(ip.image_style_callback(FakeUpdate(query=cancel_query), ctx))
        check("cancel oqimni tugatdi", cancel_state == ip.ConversationHandler.END, str(cancel_state))
        check("cancel kredit sarflamadi", calls.count("use_user_credit") == 0)

        # Yangi, mustaqil oqim sessiyasi: style bosilganda aynan bir marta.
        ctx2 = FakeContext(bot)
        msg2 = FakeMessage(photo=[photo], caption="250 000 so'm")
        run(ip.image_photo_received(FakeUpdate(message=msg2), ctx2))
        style_query = FakeQuery(f"{ip.IMAGE_STYLE_PREFIX}sales", message=msg2)
        style_state = run(ip.image_style_callback(FakeUpdate(query=style_query), ctx2))
        check("style callback natija state", style_state == ip.IMAGE_POST_RESULT, str(style_state))
        check("style callback aynan 1 credit", calls.count("use_user_credit") == 1, str(calls))
        preview = next((r for r in msg2.replies if r.get("kind") == "photo"), None)
        check("preview aynan shu photo", preview and preview["photo"] == "photo-1")
        check("preview generated caption", preview and "Sumka" in preview["caption"])
        check("preview action buttons", preview and set((ip.IMAGE_SEND, ip.IMAGE_SCHEDULE, ip.IMAGE_RESTYLE)).issubset(set(callbacks(preview["reply_markup"]))))
    finally:
        ip.analyze_image = original_analyze
        ip.generate_image_post = original_generate
        ip.db.run_db = original_run_db


def test_photo_delivery_and_scheduler_payload():
    print("== TEST 3: photo+caption delivery va scheduler payload ==")
    from handlers import image_post as ip

    captured = {}

    async def fake_runner(func, *args, **kwargs):
        captured.update(kwargs)
        return 314

    post_id = run(ip.schedule_photo_post(
        771000,
        "-1001",
        "photo-1",
        "<b>Sumka uchun ajoyib taklif!</b>",
        "2026-09-13 18:30",
        db_runner=fake_runner,
    ))
    check("scheduler post id qaytdi", post_id == 314)
    check("scheduler post_type photo", captured.get("post_type") == "photo", str(captured))
    check("scheduler file_id original photo", captured.get("file_id") == "photo-1")
    check("scheduler content generated caption", "Sumka" in captured.get("content", ""))
    check("scheduler recurrence none", captured.get("recurrence_type") == "none")

    bot = FakeBot(b"unused")
    run(ip._send_photo_to_chat(bot, "-1001", "photo-1", "<b>Caption</b>"))
    check("channel send_photo chaqirildi", len(bot.photo_calls) == 1)
    check("channel photo + caption birga", bot.photo_calls[0]["photo"] == "photo-1" and "Caption" in bot.photo_calls[0]["caption"])


def main():
    test_image_validation_contract()
    test_gemini_vision_analysis()
    test_style_credit_contract()
    test_photo_delivery_and_scheduler_payload()
    print(f"\nIMAGE → POST: {passed} OK, {failures} FAIL")
    if failures:
        raise SystemExit(1)
    print("IMAGE → POST regression testlari muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
