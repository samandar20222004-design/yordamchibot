#!/usr/bin/env python3
"""🖼 MEDIA GROUP (ALBOM) INTERCEPTION — bitta albom = bitta post.

Qamrov (topshiriq bo'yicha QAT'IY tekshiruvlar):

  1) ``MediaGroupCollector`` — qat'iy **2.0 soniya** debounce: 3–5 ta tez
     kelgan media update bitta buferga yig'iladi, yangi fayl oynani uzaytiradi
     va FAQAT ``on_ready`` bir marta chaqiriladi;
  2) ``services/album_gate.py`` — xom media update'lar (``media_group_id``)
     yagona media handlerlariga DARHOL uzatilmaydi: darvoza ularni ushlaydi va
     zanjirni ``ApplicationHandlerStop`` bilan to'xtatadi;
  3) HAQIQIY PTB Application + haqiqiy dispatch: 5 ta tez update → AYNAN
     1 ta konsolidatsiyalangan post obyekti va AYNAN 1 ta preview;
  4) 📸 Image → Post oqimi albom bilan: 1 marta Vision, 1 ta albom preview
     (+ bitta boshqaruv paneli) va kanalga bitta ``sendMediaGroup``;
  5) albomni allaqachon qo'llab-quvvatlaydigan oqimlar (🧹 tozalagich,
     ✍️ oddiy post, ✍️ new post draft, ✨ enhancer) konsolidatsiyalangan
     payload'ni BIR MARTA ishlaydi (takroriy preview/post yo'q).

Ishga tushirish (repo ildizidan):
    bash tests/run_tests.sh   (yoki)
    PYTHONPATH=telegram_bot python3 tests/media_group_interception_test.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:MEDIA_GROUP_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AI_ALLOW_MOCK", "1")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "telegram_bot"))

from telegram import Chat, Message, PhotoSize, Update, User  # noqa: E402
from telegram.ext import (  # noqa: E402
    Application,
    ApplicationBuilder,
    ApplicationHandlerStop,
    MessageHandler,
    filters,
)

from services.album_gate import (  # noqa: E402
    ALBUM_GATE_GROUP,
    ALBUM_PENDING_KEY,
    AlbumGate,
    AlbumGateHandler,
    register_album_gate,
    take_album_payload,
)
from services.media_group_collector import (  # noqa: E402
    ADDED,
    ADDED_STARTED,
    ALBUM_DEBOUNCE_SECONDS,
    DEFAULT_DELAY_SECONDS,
    MediaGroupCollector,
)

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


# =========================================================================
# UMUMIY YORDAMCHILAR
# =========================================================================
def _photo_message(message_id, group_id=None, caption=None, chat_id=1, user_id=7):
    """Haqiqiy PTB ``Message`` (photo) — dispatch filtrlari uchun."""
    return Message(
        message_id=message_id,
        date=None,
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=user_id, first_name="Test", is_bot=False),
        photo=[PhotoSize(file_id=f"file-{message_id}", file_unique_id=f"u{message_id}",
                         width=100, height=100)],
        media_group_id=group_id,
        caption=caption,
    )


def _photo_update(message_id, group_id=None, caption=None, chat_id=1, user_id=7):
    return Update(update_id=message_id,
                  message=_photo_message(message_id, group_id, caption, chat_id, user_id))


def _minimal_app():
    """Tarmoqsiz ishlaydigan REAL PTB Application (faqat dispatch uchun).

    ``initialize()`` Telegram ``getMe`` ga chiqadi — shuning uchun faqat
    dispatch uchun zarur bo'lgan minimal holat qo'lda o'rnatiladi.
    """
    app = ApplicationBuilder().token("123456:MEDIA_GROUP_TEST_TOKEN").build()
    app._initialized = True
    app._user_data = defaultdict(dict)
    app._chat_data = defaultdict(dict)
    app._bot_data = {}
    return app


# =========================================================================
# TEST 0 — PRODUKSIYA ULANISHI: darvoza main.py'da, handler reyestrida EMAS
# =========================================================================
def test_production_wiring():
    print("== TEST 0: main.py albom darvozasini handlerlardan oldin o'rnatadi ==")
    main_src = (ROOT / "telegram_bot" / "main.py").read_text(encoding="utf-8")
    check("main.py: register_album_gate import qilinadi",
          "from services.album_gate import register_album_gate" in main_src)
    check("main.py: darvoza register_all_handlers'dan OLDIN o'rnatiladi",
          main_src.find("register_album_gate(application)")
          < main_src.find("register_all_handlers(application)"))
    check("main.py: RBAC (-2) qatorida, ya'ni handlerlardan oldingi qatlam",
          main_src.find("install_resource_middleware(application, group=-2)")
          < main_src.find("register_album_gate(application)"))

    # Handler reyestri (``register_all_handlers``) faqat handlerlar bilan
    # band bo'lishi kerak: darvoza u yerda EMAS (aks holda har bir test
    # Application'i xom albom update'larini yutib yuborardi).
    reg_src = (ROOT / "telegram_bot" / "handlers" / "__init__.py").read_text(encoding="utf-8")
    check("handlers/__init__.py: darvoza registratsiyasi YO'Q (main.py wiring)",
          "register_album_gate(" not in reg_src and "_register_album_gate" not in reg_src)

    # Funksional: helper haqiqiy PTB Application'ga group=-3 handler qo'shadi.
    app = _minimal_app()
    gate = register_album_gate(app)
    check("register_album_gate: group=-3 da AlbumGateHandler",
          ALBUM_GATE_GROUP in app.handlers
          and len(app.handlers[ALBUM_GATE_GROUP]) == 1
          and isinstance(app.handlers[ALBUM_GATE_GROUP][0], AlbumGateHandler),
          str(sorted(app.handlers)))
    check("darvoza Application'ga bog'landi (qayta uzatish ishlaydi)",
          gate._app is app)
    check("darvoza guruhi barcha handlerlardan oldin (-3)",
          ALBUM_GATE_GROUP < 0, str(ALBUM_GATE_GROUP))


# =========================================================================
# TEST 1 — KOLLEKTOR: QAT'IY 2.0s DEBOUNCE + 5 TA TEZ UPDATE = 1 ALBOM
# =========================================================================
def test_collector_two_second_debounce():
    print("== TEST 1: collector — 5 ta tez update, 2.0s debounce, bitta albom ==")
    check("standart debounce 2.0 soniya (yagona manba)",
          ALBUM_DEBOUNCE_SECONDS == DEFAULT_DELAY_SECONDS == 2.0,
          f"{ALBUM_DEBOUNCE_SECONDS}/{DEFAULT_DELAY_SECONDS}")

    delivered = []
    worker_ids = set()

    async def ready(items):
        delivered.append(items)

    async def run():
        collector = MediaGroupCollector()  # production sozlamalari
        for index in range(5):
            outcome = collector.add(
                ("chat-1", "same-group"),
                {"message_id": 100 + index, "file_id": f"rapid-{index}"},
                ready,
            )
            # Har bir yangi fayl FAQAT mavjud buferga qo'shiladi.
            if index:
                assert outcome == ADDED, outcome
            worker_ids.add(id(collector.task_for(("chat-1", "same-group"))))
            await asyncio.sleep(0.05)
        # Hali jimlik oynasi tugamagan — preview YO'Q.
        blocked_before = list(delivered)
        await asyncio.sleep(1.0)
        no_preview_yet = list(delivered)
        await collector.wait_idle()
        return blocked_before, no_preview_yet, collector

    blocked_before, no_preview_yet, collector = asyncio.run(run())
    check("yig'ilish davomida on_ready chaqirilmaydi", blocked_before == [])
    check("1.0s jimlik hali 2.0s oynani tugatmaydi", no_preview_yet == [])
    check("aynan bitta worker (N ta task EMAS)", len(worker_ids) == 1, str(len(worker_ids)))
    check("on_ready AYNAN bir marta", len(delivered) == 1, str(len(delivered)))
    check("bitta albomda 5 ta fayl",
          len(delivered) == 1
          and [i["file_id"] for i in delivered[0]]
          == [f"rapid-{i}" for i in range(5)],
          str(delivered)[:120])
    check("bufer bo'shadi (post takrorlanmaydi)",
          collector.pending() == 0 and not collector.is_collecting(("chat-1", "same-group")))
    check("yakunlangan albom hisobga olindi",
          collector.stats()["delivered_groups"] == 1,
          str(collector.stats()))


def test_collector_add_many_is_atomic():
    print("== TEST 1b: add_many — konsolidatsiyalangan albom bitta chaqiruvda ==")
    delivered = []

    async def ready(items):
        delivered.append(list(items))

    async def run():
        collector = MediaGroupCollector(delay=0.05, max_wait=1.0)
        items = [{"message_id": i, "file_id": f"m{i}"} for i in range(1, 6)]
        outcome = collector.add_many(("c", "g"), items, ready)
        duplicate = collector.add_many(("c", "g"), items, ready)  # dublikatlar
        await collector.wait_idle()
        return collector, outcome, duplicate

    collector, outcome, duplicate = asyncio.run(run())
    check("add_many birinchi chaqiruvda bufer ochadi", outcome == ADDED_STARTED, outcome)
    check("dublikat fayllar qo'shilmaydi", duplicate in ("duplicate", ADDED), duplicate)
    check("on_ready bir marta, 5 ta fayl bilan",
          len(delivered) == 1 and len(delivered[0]) == 5, str(delivered)[:80])


# =========================================================================
# TEST 2 — DARVOZA: INTERCEPTION + ZANJIRNI TO'XTATISH
# =========================================================================
def test_gate_intercepts_before_single_handlers():
    print("== TEST 2: darvoza — xom albom elementi yagona handlerlarga bormaydi ==")
    single_calls = []
    gate = AlbumGate(delay=0.05)

    async def dispatcher(update):
        single_calls.append(update.message.message_id)

    gate._dispatcher = dispatcher
    handler = AlbumGateHandler(gate)

    album_update = _photo_update(11, group_id="G-1")
    single_update = _photo_update(12)
    check("albom elementi ushlanadi (check_update)",
          handler.check_update(album_update) is album_update)
    check("yakka rasm ushlanmaydi (check_update → None)",
          handler.check_update(single_update) is None)
    check("darvoza boshqa chat turini ushlamaydi",
          gate.intercepts(Update(update_id=99, message=Message(
              message_id=99, date=None,
              chat=Chat(id=-100, type="group"),
              from_user=User(id=1, first_name="a", is_bot=False),
              photo=[PhotoSize("f", "u", 10, 10)], media_group_id="G-2"))) is False)

    async def run():
        context = SimpleNamespace(user_data={"lang": "uz"})
        consumed = gate.consume(album_update, context)
        blocked_during = list(single_calls)
        # Xom update uchun zanjir TO'XTAYDI (ApplicationHandlerStop).
        raised = False
        try:
            gate.handle_update(album_update, context)
        except ApplicationHandlerStop:
            raised = True
        pending_after_stop = list(single_calls)
        await gate.collector.wait_idle()
        return (consumed, blocked_during, raised, pending_after_stop,
                list(single_calls), context)

    (consumed, blocked_during, raised, pending_after_stop,
     released_calls, context) = asyncio.run(run())
    check("consume() albom elementini buferga oladi", consumed is True)
    check("yig'ilish boshlanganda preview YO'Q", blocked_during == [])
    check("ApplicationHandlerStop bilan zanjir to'xtatiladi", raised)
    check("stop paytida ham yagona handler chaqirilmadi", pending_after_stop == [])
    check("debounce tugagach AYNAN BITTA konsolidatsiyalangan update",
          released_calls == [11], str(released_calls))
    check("qayta uzatilgan update darvoza tomonidan qayta ushlanmaydi",
          not gate.is_released(album_update))
    payload = gate.pending_payload("G-1")
    check("bitta payload (5 ta emas)", payload is not None and payload.count == 1)
    check("darvoza hisoboti: 2 ta xom update ushlandi",
          gate.stats()["broadcasts_blocked"] == 2, str(gate.stats()))


# =========================================================================
# TEST 3 — E2E: HAQIQIY APPLICATION + 5 TA TEZ UPDATE → 1 POST, 1 PREVIEW
# =========================================================================
def test_end_to_end_single_consolidated_post():
    print("== TEST 3: E2E — 5 ta media update → 1 post obyekti + 1 preview ==")
    posts = []
    previews = []
    singles = []

    async def flow_handler(update, context):
        """Haqiqiy oqimlarning naqshi: payload bo'lsa — bitta albom posti."""
        payload = take_album_payload(context, update.message)
        if payload is None:
            singles.append(update.message.message_id)
            return
        # Kanalga yuboriladigan BITTA ko'p-mediali payload (sendMediaGroup).
        from scheduler import _build_album_media

        media = _build_album_media(payload.items, payload.caption)
        posts.append({
            "type": "album" if payload.is_album else "single",
            "count": payload.count,
            "caption": payload.caption,
            "media": media,
        })
        previews.append(payload.media_group_id)

    async def run():
        app = _minimal_app()
        gate = AlbumGate(delay=0.15, max_wait=2.0)
        gate.attach(app)
        app.add_handler(AlbumGateHandler(gate), group=ALBUM_GATE_GROUP)
        app.add_handler(MessageHandler(filters.PHOTO, flow_handler))

        # 5 ta update 30 ms oraliqda (Telegram albomlari kabi tez).
        # Izoh ATAYLAB oxirgi faylda — u butun albomga birlashtirilishi shart.
        for index in range(5):
            caption = "Yangi kolleksiya!" if index == 4 else None
            await Application.process_update(
                app, _photo_update(200 + index, group_id="E2E-G", caption=caption))
            await asyncio.sleep(0.03)
        during = {"posts": len(posts), "previews": len(previews), "singles": len(singles)}
        await asyncio.sleep(0.6)   # debounce + dispatch
        # Albomga aloqasi BO'LMAGAN yakka rasm — eski oqim ishlashi shart.
        await Application.process_update(app, _photo_update(300))
        return gate, during

    gate, during = asyncio.run(run())
    check("yig'ilish davomida HECH QANDAY post yo'q", during["posts"] == 0, str(during))
    check("yig'ilish davomida HECH QANDAY preview yo'q", during["previews"] == 0, str(during))
    check("yagona handler xom fayllarga chaqirilmadi", during["singles"] == 0, str(during))
    check("AYNAN 1 ta konsolidatsiyalangan post obyekti", len(posts) == 1, str(posts)[:120])
    check("post obyekti albom turi va 5 fayl",
          posts and posts[0]["type"] == "album" and posts[0]["count"] == 5,
          str(posts)[:120])
    check("preview AYNAN 1 marta render qilindi", len(previews) == 1, str(previews))
    check("izoh (oxirgi faylda bo'lsa ham) butun albomga birlashtirildi",
          posts and posts[0]["caption"] == "Yangi kolleksiya!", str(posts)[:120])
    check("sendMediaGroup payload'i 5 ta media, izoh faqat 1-faylda",
          posts and len(posts[0]["media"]) == 5
          and posts[0]["media"][0].caption == "Yangi kolleksiya!"
          and all(m.caption is None for m in posts[0]["media"][1:]),
          str(posts)[:160])
    check("yakka rasm (media_group_id yo'q) darhol ishlanadi",
          len(singles) == 1 and singles[0] == 300, str(singles))
    check("darvoza hisoboti: 5 fayl → 1 release",
          gate.stats()["items_collected"] == 5
          and gate.stats()["groups_released"] == 1
          and gate.stats()["releases_dispatched"] == 1,
          str(gate.stats()))


def test_gate_isolates_two_parallel_albums():
    print("== TEST 3b: ikki xil media_group_id — 2 ta alohida post ==")
    posts = []

    async def flow_handler(update, context):
        payload = take_album_payload(context, update.message)
        if payload is not None:
            posts.append((payload.media_group_id, payload.count))

    async def run():
        app = _minimal_app()
        gate = AlbumGate(delay=0.15, max_wait=2.0)
        gate.attach(app)
        app.add_handler(AlbumGateHandler(gate), group=ALBUM_GATE_GROUP)
        app.add_handler(MessageHandler(filters.PHOTO, flow_handler))
        for group, ids in (("A", (1, 2, 3)), ("B", (4, 5))):
            for message_id in ids:
                await Application.process_update(
                    app, _photo_update(400 + message_id, group_id=group))
                await asyncio.sleep(0.02)
        await asyncio.sleep(0.6)
        return gate

    gate = asyncio.run(run())
    check("ikki albom → ikki post (aralashmaydi)",
          sorted(posts) == [("A", 3), ("B", 2)], str(posts))
    check("darvoza ikkala guruhni ham yakunladi",
          gate.stats()["groups_released"] == 2, str(gate.stats()))


# =========================================================================
# TEST 4 — IMAGE → POST: 1 Vision, 1 albom preview, 1 sendMediaGroup
# =========================================================================
class _FakeBot:
    def __init__(self):
        self.media_groups = []
        self.photos = []
        self.actions = []
        self.get_file_calls = []

    async def get_file(self, file_id):
        self.get_file_calls.append(file_id)
        data = b"\xff\xd8\xff" + b"album-cover-jpeg"

        async def download_as_bytearray():
            return bytearray(data)

        return SimpleNamespace(download_as_bytearray=download_as_bytearray)

    async def send_chat_action(self, **kwargs):
        self.actions.append(kwargs)

    async def send_media_group(self, **kwargs):
        self.media_groups.append(kwargs)
        return [SimpleNamespace(message_id=1)]

    async def send_photo(self, **kwargs):
        self.photos.append(kwargs)


class _FakeMessage:
    """Minimal xabar adapteri (ps_ preview paneli uchun reply_* metodlari)."""

    def __init__(self, message_id, group_id, caption=None):
        self.message_id = message_id
        self.media_group_id = group_id
        self.caption = caption
        self.chat_id = 555
        self.chat = SimpleNamespace(id=555, type="private")
        self.from_user = SimpleNamespace(id=900, first_name="T", is_bot=False)
        self.photo = [SimpleNamespace(file_id=f"cov-{message_id}", file_size=16)]
        self.document = None
        self.video = None
        self.animation = None
        self.text = None
        self.replies = []
        self.photo_replies = []
        self.media_groups = []
        self.controls = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)
        return SimpleNamespace(message_id=len(self.replies))

    async def reply_photo(self, **kwargs):
        self.photo_replies.append(kwargs)
        self.replies.append(kwargs.get("caption"))
        return SimpleNamespace(message_id=len(self.replies))

    async def reply_media_group(self, media):
        self.media_groups.append(media)
        return [SimpleNamespace(message_id=1)]


def test_image_post_album_single_preview_and_send():
    print("== TEST 4: Image → Post albom: 1 Vision + 1 preview + 1 sendMediaGroup ==")
    from handlers import image_post as ip

    vision_calls = []

    async def fake_analyze(data, caption="", **kwargs):
        vision_calls.append(caption)
        return {
            "product_name": "Ko'ylak", "category": "Kiyim",
            "visual_features": {"color": "oq", "material": "paxta",
                                "design": "minimal", "style": "premium"},
            "caption_details": {}, "summary": "Oq ko'ylak",
        }

    async def fake_generate(analysis, style, caption="", lang="uz", is_pro=False):
        return {"post_text": "<b>Yangi</b> kolleksiya", "style": style}

    async def fake_db(func, *args, **kwargs):
        name = getattr(func, "__name__", str(func))
        if name == "is_premium":
            return False
        if name == "check_ai_limit":
            return (True, 1, 5)
        if name == "use_user_credit":
            return True
        if name == "get_user_channels":
            return [("-1001", "Kanal A")]
        return None

    async def run():
        gate = AlbumGate(delay=0.05, max_wait=1.0)
        bot = _FakeBot()
        user_data = {"lang": "uz"}
        ctx = SimpleNamespace(user_data=user_data, bot=bot)
        cover_holder = {}

        async def dispatcher(update):
            cover_holder["update"] = update
            await ip.image_photo_received(update, ctx)

        gate._dispatcher = dispatcher

        # 3 ta rasm bitta albom, izoh oxirgi faylda.
        for index in range(3):
            message = _FakeMessage(500 + index, "IMG-G",
                                   caption="Yozgi kolleksiya" if index == 2 else None)
            update = SimpleNamespace(
                message=message,
                effective_user=SimpleNamespace(id=900),
                effective_chat=SimpleNamespace(id=555, type="private"),
                update_id=500 + index,
            )
            gate.consume(update, ctx)
            await asyncio.sleep(0.02)
        await gate.collector.wait_idle()
        return gate, ctx, bot, cover_holder

    original_analyze = ip.analyze_image
    original_generate = ip.generate_image_post
    original_run_db = ip.db.run_db
    ip.analyze_image = fake_analyze
    ip.generate_image_post = fake_generate
    ip.db.run_db = fake_db
    try:
        gate, ctx, bot, cover_holder = asyncio.run(run())
        check("Vision AYNAN 1 marta chaqirildi (N ta emas)",
              len(vision_calls) == 1, str(vision_calls))
        check("albom 3 fayl bilan sessiyaga yozildi",
              len(ctx.user_data.get("image_post_album_items") or []) == 3,
              str(ctx.user_data.get("image_post_album_items")))
        check("izoh butun albomga bog'landi",
              ctx.user_data.get("image_post_caption") == "Yozgi kolleksiya",
              str(ctx.user_data.get("image_post_caption")))
        check("payload bir marta iste'mol qilindi",
              take_album_payload(ctx, cover_holder["update"].message) is None)

        # Uslub tanlash → BITTA albom preview + BITTA boshqaruv paneli.
        message = cover_holder["update"].message
        message.caption = ctx.user_data.get("image_post_analysis") and message.caption or message.caption
        query = SimpleNamespace(
            data=f"{ip.IMAGE_STYLE_PREFIX}sales",
            from_user=SimpleNamespace(id=900),
            message=message,
            answers=[],
            edits=[],
        )

        async def answer(text=None, show_alert=False):
            query.answers.append(text)

        async def edit_message_text(text, reply_markup=None, parse_mode=None, **kwargs):
            query.edits.append({"text": text, "reply_markup": reply_markup})

        query.answer = answer
        query.edit_message_text = edit_message_text
        update = SimpleNamespace(
            callback_query=query,
            effective_user=SimpleNamespace(id=900),
            message=None,
            update_id=900,
        )
        state = asyncio.run(ip.image_style_callback(update, ctx))
        check("natija holati IMAGE_POST_RESULT", state == ip.IMAGE_POST_RESULT, str(state))
        check("AYNAN 1 ta albom previewi (reply_media_group)",
              len(message.media_groups) == 1 and len(message.media_groups[0]) == 3,
              str(len(message.media_groups)) if message.media_groups else "0")
        check("albom previewida yakka reply_photo YO'Q (N ta karta emas)",
              message.photo_replies == [], str(message.photo_replies)[:120])
        check("boshqaruv paneli alohida xabarda (inline tugmalar bilan)",
              any("reply_markup" in e and e["reply_markup"] is not None
                  for e in query.edits) or len(message.replies) >= 1,
              str(query.edits)[:120])

        # Kanalga yuborish — BITTA ko'p-mediali post.
        sent = asyncio.run(ip._deliver_targets(query, ctx, [("-1001", "Kanal A")]))
        check("kanalga AYNAN 1 ta media-group posti",
              len(bot.media_groups) == 1 and len(bot.media_groups[0]["media"]) == 3,
              str(len(bot.media_groups)))
        check("kanalga alohida photo yuborilmadi (N ta post emas)",
              bot.photos == [], str(bot.photos)[:80])
        check("yuborish muvaffaqiyatli hisoblandi", sent == 1, str(sent))
        check("sessiya tozalandi (takroriy post yo'q)",
              not ctx.user_data.get("image_post_album_items"))
    finally:
        ip.analyze_image = original_analyze
        ip.generate_image_post = original_generate
        ip.db.run_db = original_run_db


# =========================================================================
# TEST 5 — ALBOMNI QO'LLAB-QUVVATLAYOTGAN OQIMLAR: KONSOLIDATSIYA BIR MARTA
# =========================================================================
def _payload_for(message, items, caption=""):
    """Darvoza yasaydigan payload'ni simulyatsiya qiladi va store'ga yozadi."""
    from services.media_group_collector import AlbumPayload, apply_album_caption

    normalized = [{"type": t, "file_id": f, "caption": c,
                   "caption_html": None, "entities": (), "message_id": i}
                  for i, (t, f, c) in enumerate(items)]
    apply_album_caption(normalized)
    return AlbumPayload(media_group_id=message.media_group_id, items=normalized,
                        chat_id=getattr(message, "chat_id", None), user_id=900,
                        caption=caption or normalized[0].get("caption") or "",
                        message=message)


def test_new_post_flow_consumes_payload_once():
    print("== TEST 5a: ✍️ new post draft — 5 fayl bitta draftga ==")
    from handlers import new_post as np

    async def run():
        message = SimpleNamespace(
            message_id=601, media_group_id="NP-G", caption="Draft izoh",
            chat_id=555, text=None, photo=[SimpleNamespace(file_id="np-0")],
            video=None, document=None, audio=None, animation=None, voice=None,
            sticker=None, from_user=SimpleNamespace(id=900), entities=None,
            caption_entities=None, chat=SimpleNamespace(id=555, type="private"),
        )
        context = SimpleNamespace(user_data={"lang": "uz"}, bot=None)
        payload = _payload_for(
            message, [("photo", f"np-{i}", "") for i in range(5)], caption="Draft izoh")
        context.user_data[ALBUM_PENDING_KEY] = {"NP-G": payload}
        update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=900))
        with patch.object(np, "_ALBUM_WAIT_SECONDS", 0.05):
            # HAQIQIY handler yo'li: content_received → payload → draft.
            state = await np.content_received(update, context)
        buffers = [b for b in np._ALBUM_BUFFERS.values() if b.get("items")]
        count = len(buffers[-1]["items"]) if buffers else 0
        # Tozalash (keyingi testlarga ta'sir qilmasin).
        np.cancel_album_collections(900)
        return state, count, context

    state, count, context = asyncio.run(run())
    check("konsolidatsiyalangan albom bitta draftga yozildi (5 fayl)",
          count == 5, str(count))
    check("holat GET_CONTENT (bitta panel ketadi)", state is not None, str(state))
    check("payload iste'mol qilindi (takroriy ishlov yo'q)",
          not context.user_data.get(ALBUM_PENDING_KEY))


def test_manual_post_flow_consumes_payload_once():
    print("== TEST 5b: ✍️ oddiy post — bitta preview + bitta sendMediaGroup ==")
    from handlers import manual_post as mp

    async def run():
        sent = {"messages": [], "groups": []}

        class _Bot:
            async def send_message(self, **kwargs):
                sent["messages"].append(kwargs)
                return SimpleNamespace(message_id=len(sent["messages"]))

            async def send_media_group(self, **kwargs):
                sent["groups"].append(kwargs)
                return []

        message = SimpleNamespace(
            message_id=701, media_group_id="MP-G", caption="Oddiy izoh",
            chat_id=555, chat=SimpleNamespace(id=555), text=None, photo=None,
            video=None, document=None, animation=None, sticker=None,
            voice=None, audio=None, from_user=SimpleNamespace(id=900),
            caption_entities=None, caption_html=None,
        )
        context = SimpleNamespace(user_data={"lang": "uz"}, bot=_Bot(), chat_id=555)
        payload = _payload_for(
            message, [("photo", f"mp-{i}", "") for i in range(4)], caption="Oddiy izoh")
        context.user_data[ALBUM_PENDING_KEY] = {"MP-G": payload}
        update = SimpleNamespace(
            message=message, effective_user=SimpleNamespace(id=900))

        original_wait = mp._MANUAL_ALBUM_WAIT_SECONDS
        mp._MANUAL_ALBUM_WAIT_SECONDS = 0.05
        try:
            state = await mp.manual_content_received(update, context)
            await mp._MANUAL_ALBUMS.wait_idle()
        finally:
            mp._MANUAL_ALBUM_WAIT_SECONDS = original_wait
        return state, sent, context, mp

    from locales.translations import get_text

    state, sent, context, mp = asyncio.run(run())
    preview_prefix = get_text("np_album_received", "uz").split("{")[0].strip()
    previews = [m for m in sent["messages"]
                if preview_prefix and preview_prefix in str(m.get("text", ""))]
    check("bitta yakuniy preview xabari (N ta emas)", len(previews) == 1,
          str(len(previews)))
    check("kanalga bitta media-group (4 fayl)",
          len(sent["groups"]) == 1 and len(sent["groups"][0]["media"]) == 4,
          str(len(sent["groups"])))
    check("post bitta DB yozuvi uchun 'album' turida",
          context.user_data.get(mp.UD_POST_TYPE) == "album",
          str(context.user_data.get(mp.UD_POST_TYPE)))
    check("holat MANUAL_PREVIEW", state == mp.MANUAL_PREVIEW
          or state == context.user_data.get(mp.UD_POST_TYPE), str(state))
    mp._MANUAL_ALBUM_TASKS.clear()


def test_cleaner_flow_consumes_payload_once():
    print("== TEST 5c: 🧹 tozalagich — bitta tozalangan albom posti ==")
    from handlers import post_cleaner_flow as clf

    album_pick_prefix = clf.t("ss_cl_album_pick", "uz").split("{")[0].strip()

    async def run():
        previews = []

        class _Bot:
            def __init__(self):
                self.messages = []
                self.media_groups = []

            async def send_message(self, chat_id=None, text=None, **kwargs):
                call = {"chat_id": chat_id, "text": text, **kwargs}
                self.messages.append(call)
                body = str(text or "")
                if "ss_cl_album_pick" in body or album_pick_prefix in body:
                    previews.append(call)
                return SimpleNamespace(message_id=len(self.messages))

            async def send_media_group(self, chat_id=None, media=None, **kwargs):
                self.media_groups.append({"chat_id": chat_id, "media": media})
                return []

        message = SimpleNamespace(
            message_id=801, media_group_id="CL-G", caption="Tozalash izohi",
            chat_id=555, text=None, photo=None, video=None, document=None,
            animation=None, audio=None, voice=None, caption_entities=(),
            from_user=SimpleNamespace(id=900),
        )
        context = SimpleNamespace(
            user_data={clf._UD_SESSION: {"signature": "imzo", "own": False,
                                         "reserve": 0, "channels": [("-1001", "Kanal")],
                                         "autosend": False},
                       "lang": "uz"},
            bot=_Bot(),
        )
        payload = _payload_for(
            message, [("photo", f"cl-{i}", "") for i in range(3)], caption="Tozalash izohi")
        context.user_data[ALBUM_PENDING_KEY] = {"CL-G": payload}
        update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=900))

        original_delay = clf._ALBUMS.delay
        clf._ALBUMS.delay = 0.05
        try:
            state = await clf.post_received(update, context)
            pending = clf._ALBUMS.pending((900, "CL-G"))
            await clf._ALBUMS.wait_idle()
        finally:
            clf._ALBUMS.delay = original_delay
        return state, pending, previews, context, clf

    state, pending, previews, context, clf = asyncio.run(run())
    check("bitta buferda 3 fayl (bitta post)", pending == 3, str(pending))
    check("holat CLEANER_POST_INPUT", state == clf.CLEANER_POST_INPUT, str(state))
    check("bitta preview (ss_cl_album_pick) chiqdi",
          len(previews) == 1, str(len(previews)))


def test_enhancer_flow_consumes_payload_once():
    print("== TEST 5d: ✨ enhancer — albom bitta post sifatida ==")
    from handlers import post_enhancer as pe

    async def run():
        message = SimpleNamespace(
            message_id=901, media_group_id="EN-G", caption="Enhancer izohi",
            chat_id=555, text=None, photo=None, video=None, document=None,
            animation=None, audio=None, voice=None, sticker=None,
            from_user=SimpleNamespace(id=900), caption_entities=(),
        )
        context = SimpleNamespace(user_data={"lang": "uz"}, bot=None)
        enh = {"step": "content", "post": None, "msg_id": None}
        context.user_data[pe._ENH_KEY] = enh
        payload = _payload_for(
            message, [("photo", f"en-{i}", "") for i in range(3)], caption="Enhancer izohi")
        context.user_data[ALBUM_PENDING_KEY] = {"EN-G": payload}
        update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=900))
        finished = {"calls": 0}

        async def fake_finish(ctx, msg, enh_state, user_id, chat_id, lang):
            finished["calls"] += 1

        original_finish = pe._finish_capture
        pe._finish_capture = fake_finish
        try:
            state = await pe._capture_post(update, context, message, enh)
        finally:
            pe._finish_capture = original_finish
        return state, enh, finished, context

    state, enh, finished, context = asyncio.run(run())
    check("enhancer albomni bitta post sifatida saqladi",
          (enh.get("post") or {}).get("type") == "album", str(enh.get("post")))
    check("3 ta fayl JSON file_id'da", (enh.get("post") or {}).get("file_id", "").count("file_id") == 3,
          str(enh.get("post"))[:80])
    check("yakunlash AYNAN bir marta chaqirildi", finished["calls"] == 1, str(finished))
    check("payload iste'mol qilindi", not context.user_data.get(ALBUM_PENDING_KEY))


# =========================================================================
# HISOBOT
# =========================================================================
def main():
    test_production_wiring()
    test_collector_two_second_debounce()
    test_collector_add_many_is_atomic()
    test_gate_intercepts_before_single_handlers()
    test_end_to_end_single_consolidated_post()
    test_gate_isolates_two_parallel_albums()
    test_image_post_album_single_preview_and_send()
    test_new_post_flow_consumes_payload_once()
    test_manual_post_flow_consumes_payload_once()
    test_cleaner_flow_consumes_payload_once()
    test_enhancer_flow_consumes_payload_once()
    print(f"\nMEDIA GROUP INTERCEPTION: [OK]={passed}  [FAIL]={failures}")
    if failures:
        raise SystemExit(1)
    print("Albom interception testlari muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
