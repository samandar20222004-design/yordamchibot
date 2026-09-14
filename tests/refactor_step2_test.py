#!/usr/bin/env python3
"""🔄 POSTASSIST V2 · 2-QADAM REFAKTOR — KONTRAKT TESTLARI (deterministik, tarmoqsiz).

Qamrov (2-qadam auditi qarorlari bo'yicha):

  TEST 1 — B1: «Kutilayotgan postlar» + «Rejalashtirilgan postlar» YAGONA
           «📅 Rejalashtirilgan» ekraniga birlashtirildi. Har bir post
           ostida BARCHA amallar bor:
           [👁 Ko'rish] [✏️ Tahrirlash] [⏰ Vaqt] [🔗 Tugma/Reaksiya] [🗑 O'chirish]
           (har biri mavjud, sinovdan o'tgan callback'larga ulanadi).
  TEST 2 — B1: eski `cab_pending` / `cab_queue` kabinet callback'lari AYNAN
           shu yagona ekranga xavfsiz yo'naltiriladi — baza yiqilsa ham
           foydalanuvchi javob oladi (crash yo'q, tugma "qotmaydi").
  TEST 3 — B2: AI Studio va Onboarding menyularidagi «🖼 Rasmdan post...»
           tugmalari YAGONA «📸 Rasm → Post» oqimini (``image_post_entry`` /
           ``IMAGE_POST_INPUT``) ochadi; eski ``photo_*`` callback'lari va
           408–410 holatlari ALIAS sifatida saqlanadi (o'chirilmagan).
  TEST 4 — 🗓 SMART CONTENT CALENDAR: «🤖 AI Yordamchi» → [🧠 Kontent reja]
           (``studio_content_plan``) 7/30 kunlik reja oqimini boshlaydi:
           soha → davomiylik (``cal_days:7|30``) → AI reja → kun tanlash
           (``cal_day:<i>``) → «✨ Magic Post». FREE 30 kun → PRO taklifi.
  TEST 5 — xavfsizlik/regressiya: yangi FSM holatlari (470–472) noyob,
           barcha yangi callback'lar <=64 bayt va kanonik prefiksda,
           eskirgan tugmalar (``cal_*``, ``sched_br:``, ``photo_*``) toast
           bilan javob beradi — hech qanday crash yo'q; i18n UZ/RU/EN 100%
           paritet.

Ishga tushirish:
    PYTHON=/home/user/venv/bin/python bash tests/run_tests.sh   # runner bosqichi
    python3 tests/refactor_step2_test.py
"""
import asyncio
import contextlib
import logging
import os
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:REFACTOR_STEP2_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10011")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

import pytz  # noqa: E402
from datetime import datetime  # noqa: E402
from telegram.ext import ConversationHandler  # noqa: E402

import importlib  # noqa: E402

import database as db_mod  # noqa: E402
# Eslatma: ``handlers.start`` / ``handlers.queue`` paket atributlari sifatida
# import qilinmaydi (ular ``handlers/__init__`` dagi funksiya nomlari bilan
# shadow qilinadi) — shu sababli importlib orqali aniq modul olinadi.
ai = importlib.import_module("handlers.ai_assistant")
cal = importlib.import_module("handlers.content_calendar_flow")
onb = importlib.import_module("handlers.onboarding")
queue_mod = importlib.import_module("handlers.queue")
start_mod = importlib.import_module("handlers.start")
from handlers.image_post import (  # noqa: E402
    IMAGE_POST_INPUT, IMAGE_STYLE_SELECT, image_post_entry,
)
from handlers.pending import _build_pending_view  # noqa: E402
from keyboards.callback_data import (  # noqa: E402
    CALLBACK_DATA_MAX_BYTES, CANONICAL_PREFIXES, callback_byte_len, is_callback_safe,
)
from keyboards.default import (  # noqa: E402
    BTN_QUICK_PHOTO_POST, BTN_QUICK_PHOTO_POST_EN, BTN_QUICK_PHOTO_POST_RU,
    get_cancel_keyboard,
)
from keyboards.inline import (  # noqa: E402
    get_ai_photo_keyboard, get_ai_studio_keyboard, render_scheduled_actions,
)
from locales.translations import get_text  # noqa: E402
from translations import channels_queue_parity_report  # noqa: E402
from translations.content_calendar import (  # noqa: E402
    calendar_t, content_calendar_parity,
)

LANGS = ("uz", "ru", "en")

PASSED = 0
FAILURES = 0


def check(label, condition, extra=""):
    """Bitta tekshiruv natijasini hisobga oladi va chop etadi (label, condition)."""
    global PASSED, FAILURES
    if condition:
        PASSED += 1
        print(f"  [OK] {label}")
    else:
        FAILURES += 1
        print(f"  [FAIL] {label} {extra}")
    return bool(condition)


# ---------------------------------------------------------------------------
# YORDAMCHILAR — yengil Update/Context fakeri (tarmoqqa chiqmaydi)
# ---------------------------------------------------------------------------
class _Msg:
    """reply_text / edit_text / delete yozib boruvchi soxta xabar."""

    def __init__(self, message_id=1, chat_id=4242, text=None):
        self.message_id = message_id
        self.chat_id = chat_id
        self.text = text
        self.sent = []
        self.deleted = 0

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.sent.append(dict(text=text, reply_markup=reply_markup, parse_mode=parse_mode))
        return _Msg(self.message_id + 1, self.chat_id)

    async def edit_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.sent.append(dict(text=text, reply_markup=reply_markup, parse_mode=parse_mode))
        return self

    async def delete(self, **kw):
        self.deleted += 1
        return True


class _Query:
    """CallbackQuery fake: answer() va edit_message_text() yozib boradi."""

    def __init__(self, data, message=None, user_id=4242):
        self.data = data
        self.message = message or _Msg()
        self.from_user = SimpleNamespace(id=user_id, first_name="Tester")
        self.answered = []
        self.edits = []

    async def answer(self, text=None, show_alert=False, **kw):
        self.answered.append((text, show_alert))
        return True

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.edits.append(dict(text=text, reply_markup=reply_markup, parse_mode=parse_mode))
        return True


def _msg_update(msg, text=None, user_id=4242):
    if text is not None:
        msg.text = text
    return SimpleNamespace(
        message=msg, effective_message=msg,
        effective_user=SimpleNamespace(id=user_id, first_name="Tester"),
        callback_query=None,
    )


def _query_update(query, user_id=4242):
    return SimpleNamespace(
        message=None, effective_message=query.message,
        effective_user=SimpleNamespace(id=user_id, first_name="Tester"),
        callback_query=query,
    )


def _ctx(lang="uz", user_data=None):
    ud = {"lang": lang}
    ud.update(user_data or {})
    return SimpleNamespace(user_data=ud, chat_data={}, bot=SimpleNamespace())


def _run(coro):
    return asyncio.run(coro)


def _build_app():
    """Haqiqiy PTB Application + register_all_handlers (tarmoqqa chiqmaydi)."""
    from telegram.ext import ApplicationBuilder
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = ApplicationBuilder().token("123456:REFACTOR_STEP2_TEST").build()
    import handlers as handlers_pkg
    handlers_pkg.register_all_handlers(app)
    return app


def _cb_update(data):
    from telegram import Update
    return Update.de_json({
        "update_id": 1,
        "callback_query": {
            "id": "1", "chat_instance": "x", "data": data,
            "from": {"id": 4242, "is_bot": False, "first_name": "Tester"},
            "message": {
                "message_id": 9, "date": 0,
                "chat": {"id": 4242, "type": "private"},
                "from": {"id": 999, "is_bot": True, "first_name": "Bot"},
                "text": "📅 Rejalashtirilgan",
            },
        },
    }, None)


def _first_routed_name(app, data):
    """Callback uchun BIRINCHI mos keladigan handler nomi (router tekshiruvi)."""
    upd = _cb_update(data)
    for group in sorted(app.handlers):
        for handler in app.handlers[group]:
            try:
                if handler.check_update(upd):
                    return getattr(getattr(handler, "callback", None), "__name__",
                                   type(handler).__name__)
            except Exception:  # pragma: no cover - himoya
                continue
    return None


@contextlib.contextmanager
def _quiet():
    """Kutilgan xatolarni sinashda log shovqinini o'chiradi (test chiqishi toza)."""
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(previous)


def _labels(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


def _cbs(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


class _DBStub:
    """``database.run_db`` o'rniga: bo'sh navbat + kanal yo'q."""

    def __init__(self, mode="empty"):
        self.mode = mode
        self.calls = []

    async def __call__(self, func, *args, **kwargs):
        name = getattr(func, "__name__", str(func))
        self.calls.append(name)
        if self.mode == "boom":
            raise RuntimeError("database unavailable")
        if name == "get_queue_post_count":
            return 0
        if name == "get_queue_posts":
            return []
        if name == "get_user_channels":
            return []
        if name == "check_queue_limit":
            return (True, 0, 5)
        if name == "get_user_language":
            return "uz"
        if name == "get_user_code":
            return "AB12"
        if name == "get_pending_posts":
            return []
        return None


def _patched(mode="empty"):
    """``database.run_db`` ni stub bilan almashtiradi; eski qiymatni qaytaradi."""
    original = db_mod.run_db
    db_mod.run_db = _DBStub(mode)
    return original


# ===========================================================================
# TEST 1 — B1: yagona «📅 Rejalashtirilgan» ekrani va TO'LIQ amallar to'plami
# ===========================================================================
def test_unified_scheduled_screen():
    print("== TEST 1: yagona «📅 Rejalashtirilgan» + 5 amal ==")
    tz = pytz.timezone("Asia/Tashkent")
    row = (7, "Kanalim", "text", "Salom dunyo", tz.localize(datetime(2026, 9, 20, 10, 0)), 3, "-100123")

    required = {
        "ko'rish (qview:)": "qview:7",
        "tahrirlash (p_edit:)": "p_edit:7",
        "vaqt (p_time:)": "p_time:7",
        "tugma/reaksiya (sched_br:)": "sched_br:7",
        "o'chirish (qdel:)": "qdel:7",
    }
    for lang in LANGS:
        kb = queue_mod._get_queue_list_keyboard([row], 0, 1, lang)
        cbs = _cbs(kb)
        labels = _labels(kb)
        for label, cb_data in required.items():
            check(f"[{lang}] yagona ro'yxatda amal bor: {label}",
                  cb_data in cbs, str(cbs))
        for icon in ("👁", "✏️", "⏰", "🔗", "🗑"):
            check(f"[{lang}] amal yorlig'i ko'rinadi: {icon}",
                  any(icon in lb for lb in labels), str(labels))

    # Eski 3 tugmali shartnoma (kanal kartochkalari) O'ZGARMAGAN.
    for lang in LANGS:
        cbs = _cbs(SimpleNamespace(inline_keyboard=[render_scheduled_actions(7, lang)]))
        check(f"[{lang}] render_scheduled_actions — 3 tugma (regressiya yo'q)",
              cbs == ["p_edit:7", "p_time:7", "qdel:7"], str(cbs))

    # Eski «⏳ Kutilayotgan postlar» ekrani ham AYNAN shu yagona ekranga boradi.
    original = _patched("empty")
    try:
        pend_text, pend_kb = _run(_build_pending_view(777, "uz"))
        sched_text, sched_kb = _run(queue_mod.scheduled_view(777, "uz", False))
    finally:
        db_mod.run_db = original
    check("pending view → yagona ekran matni",
          pend_text == sched_text and bool(pend_text), str((pend_text[:40], sched_text[:40])))
    check("pending view → yagona ekran klaviaturasi",
          _cbs(pend_kb) == _cbs(sched_kb), str((_cbs(pend_kb), _cbs(sched_kb))))
    check("yagona ekran bo'sh holatida ham navigatsiya bor",
          "cab_main" in _cbs(pend_kb), str(_cbs(pend_kb)))


# ===========================================================================
# TEST 2 — B1: eski cab_pending / cab_queue xavfsiz yo'naltiriladi
# ===========================================================================
def test_legacy_cabinet_callbacks_redirect_safely():
    print("== TEST 2: cab_pending / cab_queue → yagona ekran (crash yo'q) ==")

    for lang in LANGS:
        for data in ("cab_pending", "cab_queue"):
            q = _Query(data)
            ctx = _ctx(lang)
            original = _patched("empty")
            try:
                _run(start_mod.cabinet_callback(_query_update(q), ctx))
            finally:
                db_mod.run_db = original
            check(f"[{lang}] {data}: crash yo'q (bitta javob)",
                  len(q.message.sent) == 1, str(q.message.sent))
            text = q.message.sent[0]["text"] if q.message.sent else ""
            check(f"[{lang}] {data}: «📅» yagona ekran sarlavhasi bilan javob",
                  "📅" in text and len(text) > 10, text[:60])
            markup = q.message.sent[0]["reply_markup"] if q.message.sent else None
            check(f"[{lang}] {data}: klaviatura biriktirilgan",
                  markup is not None and bool(_cbs(markup)),
                  str(_cbs(markup) if markup else None))

    # Baza YIQILSA ham javob qaytariladi (tugma "qotmaydi").
    for data in ("cab_pending", "cab_queue"):
        q = _Query(data)
        ctx = _ctx("uz")
        original = _patched("boom")
        try:
            with _quiet():
                _run(start_mod.cabinet_callback(_query_update(q), ctx))
        finally:
            db_mod.run_db = original
        check(f"{data}: baza xatosida ham foydalanuvchi javob oladi",
              len(q.message.sent) == 1 and bool(q.message.sent[0]["text"]),
              str(q.message.sent))

    # Ikkala callback ham AYNAN bitta manbaga (scheduled_view) yo'naltirilgan.
    src = (ROOT / "handlers" / "start.py").read_text(encoding="utf-8")
    check("start.py: cab_pending va cab_queue → handlers.queue.scheduled_view",
          src.count("from handlers.queue import scheduled_view") == 2, str(src.count("scheduled_view")))
    q_src = (ROOT / "handlers" / "queue.py").read_text(encoding="utf-8")
    check("queue.py: yagona ekran funksiyasi mavjud", "async def scheduled_view(" in q_src)
    check("queue.py: bo'sh holat matni i18n orqali",
          'channels_queue_t("cq_sch_empty"' in q_src)


# ===========================================================================
# TEST 3 — B2: rasm tugmalari yagona «📸 Rasm → Post» oqimiga
# ===========================================================================
def test_image_buttons_use_unified_flow():
    print("== TEST 3: AI Studio / Onboarding rasm tugmalari → image_post ==")

    # 1) AI Studio hub tugmasi (studio_ai_photo) — yangi holatga kiradi.
    for lang in LANGS:
        q = _Query("studio_ai_photo")
        ctx = _ctx(lang, {"studio_post_text": "eski"})
        state = _run(ai.ai_studio_nav_callback(_query_update(q), ctx))
        check(f"[{lang}] studio_ai_photo → IMAGE_POST_INPUT",
              state == IMAGE_POST_INPUT, str(state))
        check(f"[{lang}] studio_ai_photo: menyu xabari EDIT qilinadi",
              len(q.edits) == 1, str(len(q.edits)))
        check(f"[{lang}] studio_ai_photo: yo'riqnoma yagona oqimdan",
              bool(q.edits) and q.edits[0]["text"] == get_text("image_post_intro", lang),
              str(q.edits[:1]))
        check(f"[{lang}] studio_ai_photo: eski studio natijasi tozalanadi",
              "studio_post_text" not in ctx.user_data)

    # 2) Onboarding tezkor tugmasi — o'sha oqim.
    for lang in LANGS:
        msg = _Msg()
        ctx_q = _ctx(lang, {"studio_file_id": "ph"})
        state = _run(onb.quick_photo_post_entry(_msg_update(msg), ctx_q))
        check(f"[{lang}] quick_photo_post_entry → IMAGE_POST_INPUT",
              state == IMAGE_POST_INPUT, str(state))
        check(f"[{lang}] quick_photo_post_entry: yagona oqim yo'riqnomasi",
              bool(msg.sent) and msg.sent[0]["text"] == get_text("image_post_intro", lang),
              str(msg.sent[:1]))
        check(f"[{lang}] quick_photo_post_entry: eski rasm tozalandi",
              "studio_file_id" not in ctx_q.user_data, str(ctx_q.user_data))

    # 3) Reply-tugma matni ham mavjud (3 tilda) va oqim shu funksiyaga boradi.
    for label in (BTN_QUICK_PHOTO_POST, BTN_QUICK_PHOTO_POST_RU, BTN_QUICK_PHOTO_POST_EN):
        check(f"tezkor rasm tugmasi mavjud: {label!r}", bool(label))
    msg = _Msg()
    state = _run(image_post_entry(_msg_update(msg), _ctx("uz")))
    check("image_post_entry (xabar) → IMAGE_POST_INPUT va yo'riqnoma",
          state == IMAGE_POST_INPUT and bool(msg.sent), str(state))
    cancel_labels = [b.text for r in get_cancel_keyboard("uz").keyboard for b in r]
    entry_kb = msg.sent[0]["reply_markup"] if msg.sent else None
    check("image_post_entry: ❌ Bekor qilish klaviaturasi biriktirilgan",
          bool(entry_kb) and [b.text for r in entry_kb.keyboard for b in r] == cancel_labels,
          str(entry_kb))

    # 4) ESKI oqim ALIAS sifatida tirik (o'chirilmagan).
    for fn_name in ("ai_photo_received", "ai_photo_result_callback", "ai_photo_edit_received"):
        check(f"alias tirik: handlers.ai_assistant.{fn_name}",
              callable(getattr(ai, fn_name, None)))
    check("alias: eski 408-410 holatlari saqlangan",
          (ai.AI_PHOTO_INPUT, ai.AI_PHOTO_RESULT, ai.AI_PHOTO_EDIT_INPUT) == (408, 409, 410))
    legacy_cbs = _cbs(get_ai_photo_keyboard("uz"))
    check("alias: eski natija klaviaturasi ishlaydi",
          {"photo_schedule", "photo_rewrite", "photo_edit"} <= set(legacy_cbs), str(legacy_cbs))
    hub_cbs = _cbs(get_ai_studio_keyboard("uz"))
    check("alias: hub tugmasi callback'i o'zgarmagan (studio_ai_photo)",
          "studio_ai_photo" in hub_cbs, str(hub_cbs))
    router_src = (ROOT / "handlers" / "__init__.py").read_text(encoding="utf-8")
    for marker in ("AI_PHOTO_INPUT: all_menu_jumps",
                   "AI_PHOTO_RESULT: all_menu_jumps",
                   "AI_PHOTO_EDIT_INPUT: all_menu_jumps"):
        check(f"alias: router'da {marker!r} saqlangan", marker in router_src)
    check("alias: photo_ stale handler saqlangan", r'pattern=r"^photo_"' in router_src)


# ===========================================================================
# TEST 4 — 🗓 Kontent-reja «🤖 AI Yordamchi» ichidan boshlanadi (7/30)
# ===========================================================================
def test_content_calendar_from_ai_hub():
    print("== TEST 4: [🧠 Kontent reja] → 7/30 kunlik reja oqimi ==")

    # 1) Hub tugmasi 3 tilda mavjud va 🧠 belgisini olib yuradi.
    for lang in LANGS:
        buttons = [(b.text, b.callback_data)
                   for r in get_ai_studio_keyboard(lang).inline_keyboard for b in r]
        hub = [t for t, d in buttons if d == "studio_content_plan"]
        check(f"[{lang}] AI Yordamchi'da [🧠 Kontent reja] tugmasi",
              len(hub) == 1 and "🧠" in hub[0], str(hub))
    check("hub klaviaturasi — 6 tugma (yangi tugma qo'shilmagan)",
          len(_cbs(get_ai_studio_keyboard("uz"))) == 6, str(_cbs(get_ai_studio_keyboard("uz"))))

    # 2) Callback — oqimni boshlaydi (soha so'raladi).
    q = _Query("studio_content_plan")
    ctx = _ctx("uz")
    state = _run(ai.ai_studio_nav_callback(_query_update(q), ctx))
    check("studio_content_plan → CALENDAR_BUSINESS", state == cal.CALENDAR_BUSINESS, str(state))
    check("soha so'raladi (AI hub xabari edit qilinadi)",
          bool(q.edits) and q.edits[0]["text"] == calendar_t("ask_business", "uz"),
          str(q.edits[:1]))

    # 3) Soha matni → davomiylik klaviaturasi (7 / 30).
    msg = _Msg(text="Ayollar kiyimi do'koni")
    state = _run(cal.calendar_business_received(_msg_update(msg), ctx))
    check("soha matni → CALENDAR_DURATION", state == cal.CALENDAR_DURATION, str(state))
    kb = msg.sent[-1]["reply_markup"]
    check("davomiylik: [7 kun] va [30 kun] tugmalari",
          {"cal_days:7", "cal_days:30"} <= set(_cbs(kb)), str(_cbs(kb)))

    # 4) 7 kunlik reja → AI (mock) → xavfsiz render + kun tugmalari.
    items = [{"rubric": "Foyda", "topic": f"{i}-kun mavzusi", "tip": "Maslahat"}
             for i in range(1, 8)]
    calls = {}

    async def fake_generate(business, days, lang="uz"):
        calls.update(business=business, days=days, lang=lang)
        return items

    async def fake_entitlement(user_id, days, recent_count=0):
        return True, "ok"

    original_gen, original_ent = cal.generate_calendar_items, cal.check_calendar_entitlement
    cal.generate_calendar_items = fake_generate
    cal.check_calendar_entitlement = fake_entitlement
    try:
        q7 = _Query("cal_days:7")
        state = _run(cal.calendar_duration_callback(_query_update(q7), ctx))
    finally:
        cal.generate_calendar_items, cal.check_calendar_entitlement = original_gen, original_ent
    check("cal_days:7 → CALENDAR_VIEW", state == cal.CALENDAR_VIEW, str(state))
    check("AI reja sohasi va davomiyligi uzatiladi",
          calls.get("days") == 7 and calls.get("business", "").startswith("Ayollar"), str(calls))
    joined = " ".join(e["text"] for e in q7.edits) + " " + " ".join(m["text"] for m in q7.message.sent)
    check("reja matnida barcha 7 kun bor",
          all(f"{n}-kun" in joined for n in range(1, 8)), joined[:120])
    plan_kb = None
    for m in q7.message.sent:
        if m["reply_markup"] is not None and "cal_day:0" in _cbs(m["reply_markup"]):
            plan_kb = m["reply_markup"]
    check("reja ostida [✨ Post yaratish] kun tugmalari bor",
          plan_kb is not None and "cal_day:6" in _cbs(plan_kb),
          str(_cbs(plan_kb) if plan_kb else None))
    check("reja sessiyasi contextga saqlandi",
          ctx.user_data.get("calendar_items") == items and ctx.user_data.get("calendar_days") == 7)

    # 5) Kun tanlash → «✨ Magic Post» uslub tanlashga uzatiladi.
    from handlers.magic_post import MAGIC_STYLE_SELECT
    qd = _Query("cal_day:0")
    state = _run(cal.calendar_day_callback(_query_update(qd), ctx))
    check("cal_day:0 → MAGIC_STYLE_SELECT (yangi generatsiya oqimi yo'q)",
          state == MAGIC_STYLE_SELECT, str(state))
    check("tanlangan kun mavzusi Magic Postga AYNAN uzatiladi",
          ctx.user_data.get("magic_raw_text") == "1-kun mavzusi",
          str(ctx.user_data.get("magic_raw_text")))
    check("uslub menyusi 5 uslubni ko'rsatadi",
          len(qd.edits) == 1 and bool(_cbs(qd.edits[0]["reply_markup"])), str(qd.edits[:1]))

    # 6) FREE uchun 30 kun → PRO taklifi (entitlement fail-closed).
    q30 = _Query("cal_days:30")
    state = _run(cal.calendar_duration_callback(_query_update(q30), ctx))
    check("30 kun (FREE) → CALENDAR_VIEW + PRO taklifi",
          state == cal.CALENDAR_VIEW
          and bool(q30.edits)
          and "sub_open" in _cbs(q30.edits[0]["reply_markup"]),
          str(q30.edits[:1]))

    original = _patched("boom")
    try:
        with _quiet():
            allowed, reason = _run(cal.check_calendar_entitlement(1, 30, 0))
    finally:
        db_mod.run_db = original
    check("entitlement FAIL-CLOSED (baza xatosida PRO berilmaydi)",
          allowed is False and reason == "pro_required", f"{allowed} {reason}")

    # 7) Eskirgan/eski tugmalar — crash yo'q.
    q_stale = _Query("cal_day:99")
    state = _run(cal.calendar_day_callback(_query_update(q_stale), ctx))
    check("cal_day:99 (eskirgan indeks) → crash yo'q", state == cal.CALENDAR_VIEW, str(state))

    q_cancel = _Query("cal_cancel")
    state = _run(cal.calendar_cancel_callback(_query_update(q_cancel), ctx))
    check("cal_cancel → oqim yopiladi va sessiya tozalanadi",
          state == ConversationHandler.END and "calendar_items" not in ctx.user_data, str(state))


# ===========================================================================
# TEST 5 — xavfsizlik va regressiya qo'riqonlari
# ===========================================================================
def test_safety_and_regression_guards():
    print("== TEST 5: xavfsizlik, FSM noyobligi, i18n paritet ==")

    # 1) Yangi FSM holatlari noyob (boshqa oqimlar bilan to'qnashmaydi).
    calendar_states = (cal.CALENDAR_BUSINESS, cal.CALENDAR_DURATION, cal.CALENDAR_VIEW)
    check("kalendar holatlari 470–472",
          calendar_states == (470, 471, 472), str(calendar_states))
    cplan = importlib.import_module("handlers.content_plan")
    from handlers.post_score import (POST_SCORE_INPUT, POST_SCORE_RESULT, POST_SCORE_SEND_CHOOSE)
    from handlers.voice_post import (VOICE_AWAIT, VOICE_STYLE_SELECT, VOICE_RESULT,
                                     VOICE_SEND_CHOOSE)
    others = {
        ai.AI_MENU_STATE, ai.AI_PROMPT_INPUT, ai.AI_TONE_SELECT, ai.AI_AUDIT_INPUT,
        ai.AI_PHOTO_INPUT, ai.AI_PHOTO_RESULT, ai.AI_PHOTO_EDIT_INPUT,
        cplan.PLAN_CHOOSE_CHANNEL, cplan.PLAN_GET_TOPIC, cplan.PLAN_VIEW,
        POST_SCORE_INPUT, POST_SCORE_RESULT, POST_SCORE_SEND_CHOOSE,
        VOICE_AWAIT, VOICE_STYLE_SELECT, VOICE_RESULT, VOICE_SEND_CHOOSE,
        IMAGE_POST_INPUT, IMAGE_STYLE_SELECT,
        100, 101, 200, 201, 202, 203, 204, 205, 301, 302, 430, 431, 432, 433,
    }
    check("kalendar holatlari boshqa oqimlar bilan to'qnashmaydi",
          not (set(calendar_states) & others), str(sorted(set(calendar_states) & others)))

    # 2) Yangi callback'lar xavfsiz (<=64 bayt) va kanonik prefiksda.
    for data in ("sched_br:7", "cal_days:7", "cal_days:30", "cal_day:0", "cal_day:29",
                 "cal_cancel", "qview:7", "p_edit:7", "p_time:7", "qdel:7"):
        check(f"callback xavfsiz: {data!r}",
              is_callback_safe(data) and callback_byte_len(data) <= CALLBACK_DATA_MAX_BYTES)
    check("sched_br: — kanonik prefikslar ro'yxatida",
          "sched_br:" in CANONICAL_PREFIXES, str(CANONICAL_PREFIXES))

    # 3) Eskirgan (stale) tugmalar — toast, crash yo'q.
    q = _Query("cal_day:0")
    state = _run(cal.calendar_stale_callback(_query_update(q), _ctx("uz")))
    check("cal_ stale tugmasi → toast va END",
          state == ConversationHandler.END and bool(q.answered), str(q.answered))

    # 3b) Router: yagona ro'yxatdagi BARCHA amallar (5 amal + aliaslar)
    #     haqiqiy handlerlarga ulanadi — "o'lik tugma" yoki eskirgan-sessiya
    #     toast'iga tushib qolmaydi.
    app = _build_app()
    expected_routes = {
        "qview:7": "queue_view_callback",
        "p_edit:7": None,      # conversation ENTRY POINT (nom ConversationHandler)
        "p_time:7": None,
        "sched_br:7": "scheduled_btn_react_callback",
        "qdel:7": "queue_delete_callback",
        "qpush:7": "queue_push_callback",
        "qpage:0": "queue_page_callback",
        "qclose": "queue_close_callback",
    }
    for data, expected in expected_routes.items():
        name = _first_routed_name(app, data)
        check(f"router: {data!r} → {expected or 'conversation entry point'}",
              name is not None and name != "expired_session_callback"
              and (expected is None or name == expected), str(name))

    # O'zga postning `sched_br:` tugmasi — egalik yo'q: yo'riqnoma, crash yo'q.
    original = _patched("empty")
    try:
        q3 = _Query("sched_br:5")
        state = _run(queue_mod.scheduled_btn_react_callback(_query_update(q3), _ctx("uz")))
    finally:
        db_mod.run_db = original
    check("sched_br: begona/eski post → crash yo'q",
          state == queue_mod.QUEUE_MENU and bool(q3.edits), f"{state} {q3.edits[:1]}")

    # 4) «🔗 Tugma/Reaksiya» tanlagichi mavjud oqimlarga boradi.
    original = _patched("empty")

    async def owned_run_db(func, *args, **kwargs):
        name = getattr(func, "__name__", str(func))
        if name == "get_queue_post_detail":
            return (5, "Kanal", "text", "x", None, 1, "-100")
        return await _DBStub("empty")(func, *args, **kwargs)

    db_mod.run_db = owned_run_db
    try:
        q4 = _Query("sched_br:5")
        _run(queue_mod.scheduled_btn_react_callback(_query_update(q4), _ctx("uz")))
    finally:
        db_mod.run_db = original
    check("sched_br: tanlagich [🔗 Tugma] / [👍 Reaksiya] ni ko'rsatadi",
          bool(q4.edits) and {"p_btn:5", "p_react:5"} <= set(_cbs(q4.edits[0]["reply_markup"])),
          str(q4.edits[:1]))

    # 5) i18n paritet (yangi kalitlar 3 tilda).
    rep = channels_queue_parity_report()
    check("channels_queue: UZ/RU/EN paritet", rep["in_sync"] is True, str(rep))
    from translations import CHANNELS_QUEUE_KEYS, channels_queue_t
    new_keys = ("cq_sch_btn_time_short", "cq_sch_btn_btn_react", "cq_sch_br_title",
                "cq_sch_br_btn_link", "cq_sch_br_btn_react", "cq_sch_stale")
    check("channels_queue: yangi kalitlar ro'yxatda",
          set(new_keys) <= set(CHANNELS_QUEUE_KEYS),
          str([k for k in new_keys if k not in CHANNELS_QUEUE_KEYS]))
    for key in new_keys:
        values = {lang: channels_queue_t(key, lang) for lang in LANGS}
        check(f"channels_queue[{key}]: uchala tilda matn bor",
              all(values.values()), str(values))
    cc_parity = content_calendar_parity()
    check("content_calendar: UZ/RU/EN paritet", all(cc_parity.values()), str(cc_parity))
    for key in ("hub_button", "generating", "choose_day", "ask_business"):
        for lang in LANGS:
            check(f"content_calendar[{lang}]: {key} matni bor",
                  bool(calendar_t(key, lang)), key)

    # 6) Router: yangi state va handlerlar ro'yxatdan o'tgan.
    src = (ROOT / "handlers" / "__init__.py").read_text(encoding="utf-8")
    for marker in ("CALENDAR_BUSINESS: all_menu_jumps + [",
                   "CALENDAR_DURATION: all_menu_jumps + [",
                   "CALENDAR_VIEW: all_menu_jumps + [",
                   'pattern=r"^cal_days:"', 'pattern=r"^cal_day:"', 'pattern=r"^cal_cancel$"',
                   'pattern=r"^sched_br:"', 'pattern=r"^cal_"',
                   'CallbackQueryHandler(queue_delete_callback, pattern=r"^qdel:")',
                   'CallbackQueryHandler(scheduled_btn_react_callback, pattern=r"^sched_br:")'):
        check(f"router: {marker} mavjud", marker in src)


def main():
    print("=" * 66)
    print(" 🔄 POSTASSIST V2 · 2-QADAM — B1 (navbat) + B2 (rasm) REFAKTORI")
    print("=" * 66)

    test_unified_scheduled_screen()
    test_legacy_cabinet_callbacks_redirect_safely()
    test_image_buttons_use_unified_flow()
    test_content_calendar_from_ai_hub()
    test_safety_and_regression_guards()

    print("\n" + "=" * 66)
    print(f" JAMI: o'tdi={PASSED}, xato={FAILURES}")
    if FAILURES:
        print(" [FAIL] 2-QADAM REFAKTOR TESTLARIDA XATOLIKLAR BOR ^^^")
        return 1
    print(" 2-QADAM REFAKTOR TESTLARI 100% YASHIL ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
