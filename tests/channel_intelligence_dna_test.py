#!/usr/bin/env python3
"""🧠 PHASE B — CHANNEL INTELLIGENCE (DNA + BEST TIME + MONITORING) TEST.

Qamrov (topshiriq spetsifikatsiyasi bilan birma-bir):

  TEST 1:  📡 MONITORING — kanal postidan metama'lumot ajratish (soat/kun
           Tashkent zonasi, media faqat file_id+turi, CTA, emoji zichligi,
           matn uzunligi); media FAYLI bazaga tushmaydiganligi (schema).
  TEST 2:  🔁 IDEMPOTENCY — (channel_id, message_id) duplicate eventlar
           ON CONFLICT DO NOTHING bilan qayta yozilmaydi (funksional:
           bir xil post 2 marta → 1 qator); tahrirlangan post duplicate.
  TEST 3:  📉 INSUFFICIENT DATA — postlar < 5 ta bo'lsa DNA va Best Time
           "insufficient" qaytaradi (confidence='low', soxta raqamlar YO'Q,
           "Yetarli ma'lumot yo'q (kamida 5 ta post kerak)" xabari).
  TEST 4:  🧠 DNA — yetarli postda to'liq profil: average_post_length,
           emoji_level, cta_style, formatting_style, sample_size,
           confidence_score; natija channel_intelligence_profiles ga
           SAQLANADI (UPSERT).
  TEST 5:  ⏰ BEST TIME — soat/hafta kuni taqsimoti, peak oynasi
           ("19:00 - 21:00" formati), kartochka qatori ("🔥 Tavsiya
           etilgan vaqt: 19:00 - 21:00 (O'rtacha 450 belgi, rasm bilan)"),
           yetarli ma'lumot yo'qda soxta raqamlar uydirmaslik.
  TEST 6:  🔐 IDOR — boshqa foydalanuvchining kanal DNA/best-time so'rovi
           (service va handler darajasida) QAT'IYAN MAN etiladi (FORBIDDEN
           / "kanal topilmadi" ekrani).
  TEST 7:  🎛 UI — [🧠 Kanal DNA] [⏰ Eng yaxshi vaqt] tugmalari panelda
           (uz/ru/en), callback'lar handlerga ulangan, 64-bayt chegarasi,
           i18n pariteti; AI orkestrator promptiga DNA ulanishi (fafaqat
           egasi kanalga).

Ishga tushirish:
    PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh   # runner bosqichi
    python3 tests/channel_intelligence_dna_test.py
"""
import asyncio
import os
import sys
import warnings
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:CHANNEL_INTELLIGENCE_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10044")
os.environ.setdefault("ENVIRONMENT", "test")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

import pytz  # noqa: E402

import database as db_mod  # noqa: E402
import handlers as H  # noqa: E402
import handlers.channels as CH  # noqa: E402
from keyboards.callback_data import (  # noqa: E402
    CALLBACK_DATA_MAX_BYTES, CB_CHANNEL_BEST_TIME, CB_CHANNEL_DNA,
    callback_byte_len, is_callback_safe,
)
from keyboards.inline import render_channel_panel  # noqa: E402
from services.ai.providers import AIProvider, ProviderChain  # noqa: E402
from services.ai.orchestrator import AIOrchestrator  # noqa: E402
from services.channels.best_time import (  # noqa: E402
    MIN_POSTS_FOR_BEST_TIME, compute_best_time, format_hour, hour_window,
    render_card_lines,
)
from services.channels.dna import (  # noqa: E402
    MIN_POSTS_FOR_DNA, build_dna_system_prompt, compute_channel_dna,
    get_channel_dna,
)
from services.channels.monitoring import (  # noqa: E402
    detect_cta, emoji_density, extract_event_metadata, media_info,
)
from translations import (  # noqa: E402
    channels_queue_parity_report, channels_queue_t,
)

TZ = pytz.timezone("Asia/Tashkent")
UTC = pytz.utc

USER_ID = 777001          # kanal EGASI
OTHER_USER_ID = 999999    # begona (IDOR)
CH_ID = "-1001234567890"
CH_TITLE = "Mening kanalim"
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


# ---------------------------------------------------------------------------
# FAKE QATLAM — soxta DB store + SQL emulyatsiyasi (tarmoqqa chiqmaydi)
# ---------------------------------------------------------------------------
class FakeChannelStore:
    """channel_post_events / channels / channel_intelligence_profiles mock."""

    def __init__(self):
        self.events = {}      # (channel_id, message_id) -> row dict
        self.owners = {}      # channel_id -> user_id
        self.profiles = {}    # channel_id -> profile dict
        self.calls = []       # (name, args, kwargs)
        self.history = []     # save_channel_post_history chaqiruvlari

    # -- cursor (SQL emulyatsiyasi) -----------------------------------------
    class Cursor:
        def __init__(self, store):
            self._store = store
            self.rowcount = 0
            self._rows = []

        def execute(self, sql, params=None):
            self.rowcount = 0
            self._rows = []
            su = " ".join(str(sql).split()).upper()
            params = tuple(params or ())
            if "INSERT INTO CHANNEL_POST_EVENTS" in su:
                check_name = "ON CONFLICT" in su
                ch_id, mid = str(params[0]), int(params[1])
                key = (ch_id, mid)
                if check_name and key in self._store.events:
                    self.rowcount = 0  # ON CONFLICT DO NOTHING → duplicate
                else:
                    self._store.events[key] = dict(zip(
                        ("channel_id", "message_id", "post_hour",
                         "post_weekday", "has_media", "media_type",
                         "media_file_id", "length", "cta_detected",
                         "emoji_density"), params))
                    self.rowcount = 1
            elif "FROM CHANNEL_POST_EVENTS" in su and su.startswith("SELECT"):
                ch_id, limit = str(params[0]), int(params[1])
                rows = [r for (c, _m), r in self._store.events.items()
                        if c == ch_id]
                rows.sort(key=lambda r: r["message_id"], reverse=True)
                self._rows = [
                    (r["channel_id"], r["message_id"], r["post_hour"],
                     r["post_weekday"], r["has_media"], r["media_type"],
                     r["length"], r["cta_detected"], r["emoji_density"], None)
                    for r in rows[:limit]
                ]
            elif "FROM CHANNELS" in su and su.startswith("SELECT"):
                owner = self._store.owners.get(str(params[0]))
                self._rows = [(owner,)] if owner is not None else []
            elif "INSERT INTO CHANNEL_INTELLIGENCE_PROFILES" in su:
                ch_id = str(params[0])
                self._store.profiles[ch_id] = {
                    "channel_id": ch_id,
                    "average_post_length": params[1],
                    "avg_post_length": params[1],
                    "emoji_level": params[2],
                    "cta_style": params[3],
                    "formatting_style": params[4],
                    "top_topics": params[5] if isinstance(params[5], list)
                                  else (params[5] or "[]"),
                    "confidence": params[6],
                    "confidence_score": params[6],
                    "sample_size": params[7],
                    "updated_at": "",
                }
                self.rowcount = 1
            elif "FROM CHANNEL_INTELLIGENCE_PROFILES" in su and su.startswith("SELECT"):
                p = self._store.profiles.get(str(params[0]))
                if p:
                    self._rows = [(
                        p["channel_id"], p["average_post_length"],
                        p["emoji_level"], p["cta_style"],
                        p["formatting_style"], p["top_topics"],
                        p["confidence"], p["sample_size"], None,
                    )]
            # Boshqa so'rovlar (buni kerak emas) — jim o'tadi.

        def fetchone(self):
            return self._rows[0] if self._rows else None

        def fetchall(self):
            return list(self._rows)

    def db_cursor(self, commit: bool = False):
        @contextmanager
        def _cm():
            yield self.Cursor(self)
        return _cm()

    # -- run_db dispatcher (asinxron) ---------------------------------------
    async def run_db(self, fn, *args, **kwargs):
        name = getattr(fn, "__name__", str(fn))
        self.calls.append((name, args, tuple(sorted(kwargs.items()))))
        if name == "get_user_channels_with_tone":
            uid = args[0]
            return [(CH_ID, CH_TITLE, "friendly")] if uid == USER_ID else []
        if name == "save_channel_post_history":
            self.history.append(dict(kwargs) if kwargs else dict(zip(
                ("channel_id", "message_id", "content", "views", "post_date"),
                args)))
            return 1
        # Haqiqiy DB funksiyasi (patch'langan cursor orqali) — idempotency va
        # SQL mantig'i AYNAN production kod orqali sinanadi.
        return await asyncio.to_thread(fn, *args, **kwargs)

    # -- Real ``database`` modul funksiyalariga delegatsiya ------------------
    # Service qatlami (get_channel_dna / get_best_time) ``db_module`` ga
    # ``hasattr`` bilan qaraydi va shu nomdagi funksiyalarni ``run_db`` orqali
    # chaqiradi. Ular haqiqiy ``database`` funksiyasiga yo'naltiriladi,
    # haqiqiy funksiyalar esa patch'langan (bu store) cursor'dan foydalanadi.
    def get_channel_post_events(self, channel_id, limit=500):
        return db_mod.get_channel_post_events(channel_id, limit)

    def get_channel_owner_id(self, channel_id):
        return db_mod.get_channel_owner_id(channel_id)

    def save_channel_intelligence_profile(self, *args, **kwargs):
        return db_mod.save_channel_intelligence_profile(*args, **kwargs)

    def get_channel_intelligence_profile(self, channel_id):
        return db_mod.get_channel_intelligence_profile(channel_id)


def make_events(count=24, hour_peak=19, hour_other=18, weekday_peak=0,
                weekday_other=2, length=450, cta_count=None,
                media_count=None, emoji_density=0.009,
                channel_id=CH_ID, start_msg=5000):
    """Deterministik test eventlari (ayni sonlar — aniq tekshiruvlar uchun).

    * ``cta_count``   — qancha eventda CTA bor (default: hammasida);
    * ``media_count`` — qancha eventda media bor (default: ~60%);
    * soatlar: birinchi ``round(count * 0.6)`` tasi ``hour_peak`` da,
      qolganlari ``hour_other`` da (dominant peak aniq bo'ladi).
    """
    if cta_count is None:
        cta_count = count
    if media_count is None:
        media_count = int(round(count * 0.6))
    peak_n = int(round(count * 0.6))
    events = []
    for i in range(count):
        events.append({
            "channel_id": channel_id,
            "message_id": start_msg + i,
            "post_hour": hour_peak if i < peak_n else hour_other,
            "post_weekday": weekday_peak if i % 2 == 0 else weekday_other,
            "has_media": i < media_count,
            "media_type": "photo" if i < media_count else None,
            "length": length,
            "cta_detected": i < cta_count,
            "emoji_density": emoji_density,
        })
    return events


class _FakeDBModule:
    """AI orkestrator testi uchun minimal ``database`` modul surati."""

    def __init__(self, owner=None, profile=None):
        self.owner = owner
        self.profile = profile
        self.calls = []

    def get_channel_owner_id(self, channel_id):  # noqa: ARG001
        raise AssertionError("to'g'ridan-to'g'ri chaqirilmagani kerak")

    def get_channel_intelligence_profile(self, channel_id):  # noqa: ARG001
        raise AssertionError("to'g'ridan-to'g'ri chaqirilmagani kerak")

    async def run_db(self, fn, *args, **kwargs):
        name = getattr(fn, "__name__", str(fn))
        self.calls.append((name, args))
        if name == "get_channel_owner_id":
            return self.owner
        if name == "get_channel_intelligence_profile":
            return self.profile
        raise AssertionError(f"kutilmagan db chaqiruvi: {name}")


class _CapturingProvider(AIProvider):
    """Orkestrator testida provayderga tushgan context'ni yozib oladi."""

    name = "CaptureProvider"

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
# YORDAMCHILAR — yengil Update/Query fakeri (tarmoqqa chiqmaydi)
# ---------------------------------------------------------------------------
class _Msg:
    def __init__(self, user_id=USER_ID):
        self.from_user = SimpleNamespace(id=user_id, first_name="Tester")
        self.chat = SimpleNamespace(id=user_id, type="private")
        self.sent = []

    async def reply_text(self, text, **kwargs):
        self.sent.append(dict(text=text, **kwargs))
        return SimpleNamespace(message_id=1, chat=self.chat)


class _Query:
    def __init__(self, data, user_id=USER_ID):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id, first_name="Tester")
        self.message = _Msg(user_id)
        self.answered = []
        self.edits = []

    async def answer(self, text=None, **kwargs):
        self.answered.append(text)
        return True

    async def edit_message_text(self, text, **kwargs):
        self.edits.append(dict(text=text, **kwargs))
        return True

    async def edit_message_reply_markup(self, **kwargs):
        return True

    @property
    def screen(self):
        if self.edits:
            return self.edits[-1]
        if self.message.sent:
            return self.message.sent[-1]
        return {}


def _upd_query(query):
    return SimpleNamespace(message=None, effective_message=query.message,
                           effective_user=query.from_user,
                           callback_query=query)


def _ctx(lang="uz"):
    return SimpleNamespace(user_data={"lang": lang}, chat_data={},
                           bot=SimpleNamespace(username="postassist_test_bot"),
                           application=None)


def _with_db(store, coro_factory):
    """``db.run_db`` va ``db.db_cursor`` ni store bilan almashtiradi."""
    original_run = db_mod.run_db
    original_cur = db_mod.db_cursor
    db_mod.run_db = store.run_db
    db_mod.db_cursor = store.db_cursor
    try:
        return asyncio.run(coro_factory())
    finally:
        db_mod.run_db = original_run
        db_mod.db_cursor = original_cur


def _channel_post_update(message_id, text, date=None, with_photo=True):
    """Haqiqiy PTB ``Update`` (channel_post) — router/handler testlari uchun."""
    from telegram import Update
    date = date or datetime(2026, 9, 16, 14, 0, 0)  # UTC → Tashkent 19:00
    payload = {
        "update_id": 100,
        "channel_post": {
            "message_id": message_id,
            "date": int(date.replace(tzinfo=UTC).timestamp()),
            "chat": {"id": int(CH_ID), "type": "channel", "title": CH_TITLE},
            "text": text,
        },
    }
    if with_photo:
        payload["channel_post"]["photo"] = [
            {"file_id": "AgACAgUAAx0D", "file_unique_id": "uq1", "width": 900,
             "height": 600, "file_size": 12345},
        ]
    return Update.de_json(payload, None)


# ---------------------------------------------------------------------------
# TEST 1 — 📡 MONITORING: metama'lumot ajratish
# ---------------------------------------------------------------------------
def test_monitoring_metadata_extraction():
    print("\n== TEST 1: 📡 Monitoring — post metama'lumotlari (pure) ==")

    msg = _channel_post_update(
        77001,
        "🔥 Yangi mahsulot! Buyurtma bering 👉 hamda obuna bo'ling ✨",
        date=datetime(2026, 9, 16, 14, 0, 0),  # UTC
    )
    cp = msg.channel_post
    meta = extract_event_metadata(cp)

    check("channel_id to'g'ri", meta["channel_id"] == CH_ID, str(meta["channel_id"]))
    check("message_id to'g'ri", meta["message_id"] == 77001, str(meta["message_id"]))
    # UTC 14:00 → Tashkent (UTC+5) 19:00
    check("post_hour Tashkent zonasi (UTC+5)", meta["post_hour"] == 19,
          str(meta["post_hour"]))
    # 2026-09-16 — Chorshanba (weekday=2)
    check("post_weekday to'g'ri (Chorshanba=2)", meta["post_weekday"] == 2,
          str(meta["post_weekday"]))
    check("has_media (rasm bor)", meta["has_media"] is True)
    check("media_type = photo", meta["media_type"] == "photo", str(meta["media_type"]))
    check("media file_id faqat ID (turi bilan)", bool(meta["media_file_id"])
          and "AgACAgUAAx0D" in meta["media_file_id"], str(meta["media_file_id"]))
    check("length = matn uzunligi",
          meta["length"] == len("🔥 Yangi mahsulot! Buyurtma bering 👉 hamda obuna bo'ling ✨"),
          str(meta["length"]))
    check("cta_detected (Buyurtma/obuna)", meta["cta_detected"] is True)
    check("emoji_density > 0", meta["emoji_density"] > 0, str(meta["emoji_density"]))

    # Pure funksiya'lar
    check("detect_cta: buyurtma", detect_cta("Hoziroq buyurtma bering!") is True)
    check("detect_cta: subscribe (en)", detect_cta("Subscribe to our channel") is True)
    check("detect_cta: подписка (ru)", detect_cta("Подписка обязательна") is True)
    check("detect_cta: CTA'siz matn", detect_cta("Oddiy ma'lumot matni") is False)
    check("emoji_density: bo'sh matn = 0", emoji_density("") == 0.0)
    d1 = emoji_density("Salom 😊😊😊 bu yerda 3 emoji bor")
    check("emoji_density: qiymat 0..1 oralig'ida", 0 < d1 <= 1, str(d1))

    has, mtype, fid = media_info(SimpleNamespace(photo=None, video=None,
                                                 document=None, audio=None,
                                                 animation=None, sticker=None,
                                                 poll=None, video_note=None))
    check("media_info: media'siz xabar", has is False and mtype is None and fid is None)

    # Video post — media turi va file_id
    vid_msg = SimpleNamespace(
        video=SimpleNamespace(file_id="BD_VIDEO_123"), video_note=None,
        animation=None, audio=None, document=None, photo=None, sticker=None,
        poll=None, text="Video post",
    )
    has, mtype, fid = media_info(vid_msg)
    check("media_info: video file_id", has is True and mtype == "video"
          and fid == "BD_VIDEO_123", f"{has}/{mtype}/{fid}")

    # Xavfsizlik: media FAYLI (mazmuni) bazaga tushmaydi — schema'da blob/bytea yo'q
    schema_text = (ROOT / "schema.sql").read_text(encoding="utf-8")
    events_block = schema_text.split("CREATE TABLE IF NOT EXISTS channel_post_events", 1)[1]
    events_block = events_block.split(");", 1)[0]
    check("schema: channel_post_events da BYTEA/BLOB yo'q (faqat file_id)",
          "BYTEA" not in events_block.upper() and "BLOB" not in events_block.upper(),
          events_block[:200])
    check("schema: media_file_id VARCHAR (faqat ID)", "media_file_id VARCHAR" in events_block)
    check("schema: media_type ustuni", "media_type VARCHAR" in events_block)
    check("schema: emoji_density ustuni", "emoji_density" in events_block)
    check("schema: UNIQUE(channel_id, message_id) saqlangan",
          "UNIQUE(channel_id,message_id)" in events_block.replace(" ", ""))


# ---------------------------------------------------------------------------
# TEST 2 — 🔁 IDEMPOTENCY: duplicate eventlar yozilmaydi
# ---------------------------------------------------------------------------
def test_event_idempotency():
    print("\n== TEST 2: 🔁 Idempotency — ON CONFLICT DO NOTHING (funksional) ==")
    store = FakeChannelStore()
    db_src = (ROOT / "database.py").read_text(encoding="utf-8")
    ins_sql = db_src.split("def insert_channel_post_event", 1)[1].split("\ndef ", 1)[0]
    check("SQL: ON CONFLICT (channel_id, message_id) DO NOTHING",
          "ON CONFLICT (channel_id, message_id) DO NOTHING" in ins_sql, ins_sql[:300])

    def _run():
        async def go():
            r1 = db_mod.insert_channel_post_event(
                CH_ID, 80001, post_hour=19, post_weekday=4, has_media=True,
                media_type="photo", media_file_id="AgACAgUAAx0D",
                length=450, cta_detected=True, emoji_density=0.008)
            r2 = db_mod.insert_channel_post_event(
                CH_ID, 80001, post_hour=19, post_weekday=4, has_media=True,
                media_type="photo", media_file_id="AgACAgUAAx0D",
                length=450, cta_detected=True, emoji_density=0.008)
            r3 = db_mod.insert_channel_post_event(
                CH_ID, 80002, post_hour=20, post_weekday=4, has_media=False,
                media_type=None, media_file_id=None,
                length=300, cta_detected=False, emoji_density=0.002)
            return r1, r2, r3
        return go()

    r1, r2, r3 = _with_db(store, _run)
    check("birinchi insert → True (yangi)", r1 is True, str(r1))
    check("dublikat insert → False (DO NOTHING)", r2 is False, str(r2))
    check("boshqa message_id → True", r3 is True, str(r3))
    check("bazada AYNAN 2 qator (dublikat yozilmadi)",
          len(store.events) == 2, str(list(store.events)))

    # get_channel_post_events orqali ham tasdiqlaymiz
    def _run2():
        async def go():
            return db_mod.get_channel_post_events(CH_ID, 100)
        return go()
    rows = _with_db(store, _run2)
    check("get_channel_post_events: 2 qator qaytadi", len(rows) == 2, str(len(rows)))
    check("qator maydonlari to'liq",
          rows[0]["message_id"] in (80001, 80002)
          and "post_hour" in rows[0] and "emoji_density" in rows[0], str(rows[:1]))

    # message_id'siz insert xavfsiz (skip) — xato ko'tarmaydi
    def _run3():
        async def go():
            return db_mod.insert_channel_post_event(CH_ID, None, post_hour=19)
        return go()
    r_none = _with_db(store, _run3)
    check("message_id=None → False (xavfsiz skip)", r_none is False, str(r_none))
    check("store o'zgarmadi", len(store.events) == 2, str(len(store.events)))


# ---------------------------------------------------------------------------
# TEST 3 — 📉 INSUFFICIENT DATA: < 5 post
# ---------------------------------------------------------------------------
def test_insufficient_data():
    print("\n== TEST 3: 📉 Kam post (<5) — insufficient data ==")
    check("minimal chegara: DNA=5, BEST_TIME=5",
          MIN_POSTS_FOR_DNA == 5 and MIN_POSTS_FOR_BEST_TIME == 5)

    few = make_events(4)
    dna = compute_channel_dna(few)
    check("DNA: 4 post → insufficient", dna["insufficient"] is True)
    check("DNA: confidence='low'", dna["confidence"] == "low", str(dna["confidence"]))
    check("DNA: soxta profil YO'Q (profile=None)", dna["profile"] is None)
    check("DNA: aniq xabar",
          dna["message"] == "Yetarli ma'lumot yo'q (kamida 5 ta post kerak)",
          str(dna["message"]))
    check("DNA: sample_size aniq (4)", dna["sample_size"] == 4, str(dna["sample_size"]))

    dna0 = compute_channel_dna([])
    check("DNA: 0 post → insufficient", dna0["insufficient"] is True
          and dna0["sample_size"] == 0)

    bt = compute_best_time(few)
    check("BestTime: 4 post → insufficient", bt["insufficient"] is True)
    check("BestTime: soxta raqamlar YO'Q (peak_hour=None)",
          bt["peak_hour"] is None and bt["top_window"] is None, str(bt["peak_hour"]))
    check("BestTime: top_windows bo'sh", bt["top_windows"] == [])
    check("BestTime: aniq xabar",
          bt["message"] == "Yetarli ma'lumot yo'q (kamida 5 ta post kerak)")

    # Service darajasi: kam event → insufficient + DB'ga profil SAQLANMAYDI
    store = FakeChannelStore()
    store.owners[CH_ID] = USER_ID
    for ev in few:
        store.events[(ev["channel_id"], ev["message_id"])] = ev

    def _run():
        async def go():
            res_dna = await get_channel_dna(CH_ID, user_id=USER_ID, db_module=store)
            return res_dna
        return go()
    res = _with_db(store, _run)
    check("service: insufficient=True qaytadi", res.get("ok") is True
          and res.get("insufficient") is True, str(res)[:160])
    check("service: confidence='low'", res.get("confidence") == "low")
    check("service: soxta raqamlar yo'q (sample=4)", res.get("sample_size") == 4)
    check("service: kam ma'lumotda profil SAQLANMAYDI", store.profiles == {})


# ---------------------------------------------------------------------------
# TEST 4 — 🧠 DNA: yetarli postda to'liq profil
# ---------------------------------------------------------------------------
def test_dna_sufficient_data():
    print("\n== TEST 4: 🧠 DNA — yetarli postlarda to'liq profil ==")
    events = make_events(24, length=450, cta_count=24, media_count=14,
                         emoji_density=0.009)
    dna = compute_channel_dna(events)
    check("insufficient=False", dna["insufficient"] is False)
    check("sample_size=24", dna["sample_size"] == 24, str(dna["sample_size"]))

    p = dna["profile"]
    check("average_post_length=450", p["average_post_length"] == 450, str(p))
    check("emoji_level o'rtacha (0.009)", p["emoji_level"] == "medium",
          str(p["emoji_level"]))
    check("cta_style=always (100%)", p["cta_style"] == "always", str(p["cta_style"]))
    check("formatting_style=media_rich (60% rasm)",
          p["formatting_style"] == "media_rich", str(p["formatting_style"]))
    check("confidence_score: 20+ post → 90", p["confidence_score"] == 90,
          str(p["confidence_score"]))
    check("confidence darajasi: 20+ → high", dna["confidence"] == "high",
          str(dna["confidence"]))

    # Emoji darajalarining chegaralari
    check("emoji: 0 → low", compute_channel_dna(
        make_events(6, emoji_density=0.0))["profile"]["emoji_level"] == "low")
    check("emoji: 0.02 → high", compute_channel_dna(
        make_events(6, emoji_density=0.02))["profile"]["emoji_level"] == "high")
    # CTA nozly
    check("cta_style=none (0%)", compute_channel_dna(
        make_events(6, cta_count=0))["profile"]["cta_style"] == "none")

    # Prompt bloki (AI uchun) — ixcham va ma'lumotli
    prompt = build_dna_system_prompt(p, "uz")
    check("prompt: KANAL USLUBI (DNA) belgisi", "KANAL USLUBI (DNA)" in prompt, prompt)
    check("prompt: o'rtacha uzunlik", "450 belgi" in prompt, prompt)
    check("prompt: RU versiyasi", "СТИЛЬ КАНАЛА (DNA)" in build_dna_system_prompt(p, "ru"))
    check("prompt: EN versiyasi", "CHANNEL STYLE (DNA)" in build_dna_system_prompt(p, "en"))
    check("prompt: kam ma'lumotda BO'SH (soxta uslub yo'q)",
          build_dna_system_prompt({"average_post_length": 450, "sample_size": 3}, "uz") == "")

    # Service: profil channel_intelligence_profiles ga UPSERT qilinadi
    store = FakeChannelStore()
    store.owners[CH_ID] = USER_ID
    for ev in events:
        store.events[(ev["channel_id"], ev["message_id"])] = ev

    def _run():
        async def go():
            return await get_channel_dna(CH_ID, user_id=USER_ID, db_module=store)
        return go()
    res = _with_db(store, _run)
    check("service: ok=True, insufficient=False",
          res.get("ok") is True and res.get("insufficient") is False, str(res)[:160])
    check("service: profile qaytadi",
          res.get("profile", {}).get("average_post_length") == 450, str(res.get("profile")))
    check("service: saved=True (DB'ga yozildi)", res.get("saved") is True, str(res.get("saved")))
    check("DB: channel_intelligence_profiles ga UPSERT qilindi",
          CH_ID in store.profiles and store.profiles[CH_ID]["sample_size"] == 24,
          str(store.profiles)[:200])
    check("DB: confidence INT saqlandi (90)",
          store.profiles[CH_ID]["confidence"] == 90)
    check("DB: formatting_style saqlandi",
          store.profiles[CH_ID]["formatting_style"] == "media_rich")
    check("chaqiruvlar: get_channel_post_events + save profil",
          any(c[0] == "get_channel_post_events" for c in store.calls)
          and any(c[0] == "save_channel_intelligence_profile" for c in store.calls),
          str([c[0] for c in store.calls]))


# ---------------------------------------------------------------------------
# TEST 5 — ⏰ BEST TIME: taqsimot, peak oyna, kartochka
# ---------------------------------------------------------------------------
def test_best_time_generator():
    print("\n== TEST 5: ⏰ Best Time — peak oyna va kartochka ==")
    events = make_events(24, hour_peak=19, hour_other=18,
                         weekday_peak=0, weekday_other=2,
                         length=450, media_count=14)
    bt = compute_best_time(events)
    check("insufficient=False", bt["insufficient"] is False)
    check("sample_size=24", bt["sample_size"] == 24)
    check("peak_hour=19 (dominant)", bt["peak_hour"] == 19, str(bt["peak_hour"]))
    check("top_window='19:00 - 21:00'", bt["top_window"] == "19:00 - 21:00",
          str(bt["top_window"]))
    check("top_windows top-3 (peak boshda)",
          bt["top_windows"][0] == ("19:00 - 21:00", 14)
          and len(bt["top_windows"]) == 2, str(bt["top_windows"]))
    check("hour_distribution bor (19→14)",
          bt["hour_distribution"].get("19") == 14, str(bt["hour_distribution"]))
    check("weekday_distribution bor",
          sum(bt["weekday_distribution"].values()) == 24,
          str(bt["weekday_distribution"]))
    check("best_weekdays (top-3, Dushanba boshda)",
          bt["best_weekdays"][0] == "Dushanba" and len(bt["best_weekdays"]) <= 3,
          str(bt["best_weekdays"]))
    check("average_length=450", bt["average_length"] == 450)
    check("media_ratio=14/24", abs(bt["media_ratio"] - 14/24) < 0.001, str(bt["media_ratio"]))

    # Oyna chegaralari (soxta vaqt yo'q: 24:00 mavjud emas)
    check("hour_window(19) = 19:00 - 21:00", hour_window(19) == "19:00 - 21:00")
    check("hour_window(22) = 22:00 - 23:00 (24:00 yo'q)", hour_window(22) == "22:00 - 23:00")
    check("hour_window(0) = 00:00 - 02:00", hour_window(0) == "00:00 - 02:00")
    check("format_hour(7) = 07:00", format_hour(7) == "07:00")

    # Kartochka qatori (spek namunasiga bir xil format)
    window_line, extra = render_card_lines(bt, "uz")
    check("kartochka: 🔥 Tavsiya etilgan vaqt",
          "🔥 Tavsiya etilgan vaqt: 19:00 - 21:00" in window_line, window_line)
    check("kartochka: O'rtacha 450 belgi, rasm bilan",
          "O'rtacha 450 belgi, rasm bilan" in window_line, window_line)
    check("kartochka: top soatlar qatori bor",
          any("Top soatlar" in x for x in extra), str(extra))
    check("kartochka: eng faol kunlar qatori bor",
          any("Eng faol kunlar" in x for x in extra), str(extra))

    window_ru, _ = render_card_lines(bt, "ru")
    check("kartochka RU: Рекомендуемое время",
          "Рекомендуемое время: 19:00 - 21:00" in window_ru, window_ru)
    window_en, _ = render_card_lines(bt, "en")
    check("kartochka EN: Suggested time", "Suggested time: 19:00 - 21:00" in window_en,
          window_en)

    # Kam ma'lumotda kartochka — soxta raqamlar YO'Q
    few = make_events(3)
    ins_line, ins_extra = render_card_lines(compute_best_time(few), "uz")
    check("kam ma'lumot: xabar qaytadi, raqamlar uydirmaydi",
          "Yetarli ma'lumot yo'q" in ins_line and ins_extra == [], str(ins_line))


# ---------------------------------------------------------------------------
# TEST 6 — 🔐 IDOR: boshqa foydalanuvchining kanali QAT'IYAN MAN
# ---------------------------------------------------------------------------
def test_idor_protection():
    print("\n== TEST 6: 🔐 IDOR — begona kanal DNA/vaqt ochilmaydi ==")
    store = FakeChannelStore()
    store.owners[CH_ID] = USER_ID
    for ev in make_events(12):
        store.events[(ev["channel_id"], ev["message_id"])] = ev

    # --- Service darajasi ---
    def _run():
        async def go():
            dna_foreign = await get_channel_dna(CH_ID, user_id=OTHER_USER_ID,
                                                 db_module=store)
            from services.channels.best_time import get_best_time
            bt_foreign = await get_best_time(CH_ID, user_id=OTHER_USER_ID,
                                              db_module=store)
            dna_owner = await get_channel_dna(CH_ID, user_id=USER_ID, db_module=store)
            return dna_foreign, bt_foreign, dna_owner
        return go()
    dna_foreign, bt_foreign, dna_owner = _with_db(store, _run)
    check("service DNA: begona user → ok=False", dna_foreign.get("ok") is False,
          str(dna_foreign)[:160])
    check("service DNA: error_code=FORBIDDEN",
          dna_foreign.get("error_code") == "FORBIDDEN", str(dna_foreign.get("error_code")))
    check("service DNA: ma'lumot ochilmadi (profile yo'q)",
          dna_foreign.get("profile") is None)
    check("service BestTime: begona user → FORBIDDEN",
          bt_foreign.get("ok") is False
          and bt_foreign.get("error_code") == "FORBIDDEN", str(bt_foreign)[:160])
    check("service BestTime: soxta raqamlar yo'q",
          bt_foreign.get("top_window") is None and bt_foreign.get("peak_hour") is None)
    check("service DNA: EGASA ochildi (ok=True)",
          dna_owner.get("ok") is True and dna_owner.get("insufficient") is False,
          str(dna_owner)[:160])

    # --- Handler darajasi (UI) ---
    q = _Query(f"{CB_CHANNEL_DNA}{CH_ID}", user_id=OTHER_USER_ID)
    state = _with_db(store, lambda: CH.channel_dna_callback(_upd_query(q), _ctx("uz")))
    screen = q.screen.get("text", "")
    check("handler DNA: begona kanal → END", state is not None, str(state))
    check("handler DNA: kanal ma'lumotlari EKRANDA YO'Q",
          "Namuna:" not in screen and "Ishonchlilik:" not in screen and "average" not in screen,
          screen[:160])
    check("handler DNA: tushunarli 'topilmadi' xabari",
          channels_queue_t("cq_ch_not_found", "uz")[:20] in screen, screen[:100])

    q2 = _Query(f"{CB_CHANNEL_BEST_TIME}{CH_ID}", user_id=OTHER_USER_ID)
    _with_db(store, lambda: CH.channel_best_time_callback(_upd_query(q2), _ctx("uz")))
    screen2 = q2.screen.get("text", "")
    check("handler BestTime: begona kanal → xato xabari",
          channels_queue_t("cq_ch_not_found", "uz")[:20] in screen2, screen2[:100])
    check("handler BestTime: soxta vaqt YO'Q", "Tavsiya etilgan vaqt:" not in screen2,
          screen2[:120])

    # --- Orkestrator darajasi: DNA faqat egasi kanalga ulanadi ---
    def _run_orch():
        async def go():
            from services.channels.dna import attach_dna_to_context
            ctx_foreign = {"channel_id": CH_ID, "system_prompt": "BASE",
                           "lang": "uz"}
            ctx_owner = {"channel_id": CH_ID, "system_prompt": "BASE",
                         "lang": "uz"}
            await attach_dna_to_context(ctx_foreign, OTHER_USER_ID, store)
            await attach_dna_to_context(ctx_owner, USER_ID, store)
            return ctx_foreign, ctx_owner
        return go()
    ctx_foreign, ctx_owner = _with_db(store, _run_orch)
    check("orchestrator ctx: BEGONA kanalga DNA ulanmadi",
          "DNA" not in ctx_foreign.get("system_prompt", ""),
          str(ctx_foreign.get("system_prompt"))[:120])
    check("orchestrator ctx: EGASI kanalga DNA ulandi",
          "KANAL USLUBI (DNA)" in ctx_owner.get("system_prompt", ""),
          str(ctx_owner.get("system_prompt"))[:160])


# ---------------------------------------------------------------------------
# TEST 7 — 🎛 UI: tugmalar, routing, kartochkalar, orkestrator integratsiyasi
# ---------------------------------------------------------------------------
def _build_app():
    from telegram.ext import ApplicationBuilder
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = ApplicationBuilder().token("123456:CHANNEL_INTELLIGENCE_TEST").build()
    H.register_all_handlers(app)
    return app


def _cb_update(data, user_id=USER_ID):
    from telegram import Update
    return Update.de_json({
        "update_id": 1,
        "callback_query": {
            "id": "cbq-1",
            "from": {"id": user_id, "is_bot": False, "first_name": "Tester"},
            "chat_instance": "ci-1",
            "data": data,
            "message": {
                "message_id": 5, "date": 0,
                "chat": {"id": user_id, "type": "private"},
                "from": {"id": 1, "is_bot": True, "first_name": "Bot"},
            },
        },
    }, None)


def _handler_for(app, update):
    for group in sorted(app.handlers):
        for h in app.handlers[group]:
            res = h.check_update(update)
            if res is not None and res is not False:
                return h
    return None


def test_ui_and_integration():
    print("\n== TEST 7: 🎛 UI — tugmalar, routing, orkestrator DNA ulanishi ==")

    # --- Panel: ikkala yangi tugma 3 tilda ---
    for lang in LANGS:
        kb = render_channel_panel(CH_ID, lang)
        cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
        labels = [b.text for row in kb.inline_keyboard for b in row]
        check(f"[{lang}] panel: 🧠 Kanal DNA tugmasi",
              f"{CB_CHANNEL_DNA}{CH_ID}" in cbs, str(cbs))
        check(f"[{lang}] panel: ⏰ Eng yaxshi vaqt tugmasi",
              f"{CB_CHANNEL_BEST_TIME}{CH_ID}" in cbs, str(cbs))
        check(f"[{lang}] yorliqlar tarjima qilingan",
              any("DNA" in t for t in labels) and any("⏰" in t for t in labels),
              str(labels))

    # --- 64 bayt chegarasi (uzun kanal ID) ---
    long_id = "-100" + "9" * 40
    kb_long = render_channel_panel(long_id, "ru")
    oversized = [c for c in (b.callback_data for row in kb_long.inline_keyboard
                             for b in row) if callback_byte_len(c) > CALLBACK_DATA_MAX_BYTES]
    check("uzun channel_id: callback'lar <= 64 bayt", not oversized, str(oversized))
    check("uzun channel_id: callback'lar is_callback_safe",
          all(is_callback_safe(c) for c in (b.callback_data for row in kb_long.inline_keyboard
                                            for b in row)))

    # --- Routing: barcha callback'lar handlerga ulangan ---
    app = _build_app()
    h_dna = _handler_for(app, _cb_update(f"{CB_CHANNEL_DNA}{CH_ID}"))
    h_btm = _handler_for(app, _cb_update(f"{CB_CHANNEL_BEST_TIME}{CH_ID}"))
    check("routing: ch_dna: handler topildi",
          h_dna is not None and getattr(h_dna, "callback", None) is CH.channel_dna_callback,
          str(h_dna))
    check("routing: ch_btm: handler topildi",
          h_btm is not None
          and getattr(h_btm, "callback", None) is CH.channel_best_time_callback,
          str(h_btm))

    # --- DNA kartochka: to'liq ma'lumot (owner) ---
    store = FakeChannelStore()
    store.owners[CH_ID] = USER_ID
    for ev in make_events(24, length=450, media_count=14):
        store.events[(ev["channel_id"], ev["message_id"])] = ev

    q = _Query(f"{CB_CHANNEL_DNA}{CH_ID}")
    state = _with_db(store, lambda: CH.channel_dna_callback(_upd_query(q), _ctx("uz")))
    text = q.screen.get("text", "")
    check("DNA ekran: owner uchun ochiladi", bool(text), str(state))
    check("DNA ekran: sarlavha (Kanal DNA)", "Kanal DNA" in text and CH_TITLE in text,
          text[:160])
    check("DNA ekran: o'rtacha uzunlik 450", "450 belgi" in text, text[:240])
    # Yorliq HTML-escape qilingan bo'lishi mumkin (o'rtacha → o&#x27;rtacha) —
    # Telegramda ikkala ko'rinish ham "o'rtacha" deb ko'rinadi.
    check("DNA ekran: emoji darajasi (o'rtacha)",
          "o'rtacha" in text or "o&#x27;rtacha" in text, text[:240])
    check("DNA ekran: CTA uslub", "CTA" in text, text[:240])
    check("DNA ekran: namuna 24 ta post", "24 ta post" in text, text[:240])
    check("DNA ekran: ishonchlilik balli", "/100" in text, text[:240])
    check("DNA ekran: panel tugmalari bilan qaytadi (kanal ichida qoladi)",
          q.screen.get("reply_markup") is not None)

    # --- Best-time kartochka: to'liq ma'lumot (owner) ---
    q2 = _Query(f"{CB_CHANNEL_BEST_TIME}{CH_ID}")
    _with_db(store, lambda: CH.channel_best_time_callback(_upd_query(q2), _ctx("uz")))
    text2 = q2.screen.get("text", "")
    check("BestTime ekran: sarlavha", "Eng yaxshi vaqt" in text2 and CH_TITLE in text2,
          text2[:160])
    check("BestTime ekran: 🔥 tavsiya qatori (19:00 - 21:00)",
          "🔥 Tavsiya etilgan vaqt: 19:00 - 21:00" in text2, text2[:240])
    check("BestTime ekran: O'rtacha 450 belgi, rasm bilan",
          "O'rtacha 450 belgi, rasm bilan" in text2, text2[:240])
    check("BestTime ekran: kuzatuv soni (24)", "24 ta post" in text2, text2[:240])

    # --- Best-time: kam ma'lumot → soxta raqamlarsiz ekran ---
    store_few = FakeChannelStore()
    store_few.owners[CH_ID] = USER_ID
    for ev in make_events(3):
        store_few.events[(ev["channel_id"], ev["message_id"])] = ev
    q3 = _Query(f"{CB_CHANNEL_BEST_TIME}{CH_ID}")
    _with_db(store_few, lambda: CH.channel_best_time_callback(_upd_query(q3), _ctx("uz")))
    text3 = q3.screen.get("text", "")
    check("BestTime kam: 'Yetarli ma'lumot yo'q' xabari",
          "Yetarli ma'lumot yo'q" in text3, text3[:200])
    check("BestTime kam: soxta vaqt YO'Q", "Tavsiya etilgan vaqt:" not in text3,
          text3[:200])

    # --- i18n pariteti (yangi kalitlar bilan) ---
    rep = channels_queue_parity_report()
    check("i18n: channels_queue pariteti in_sync", rep["in_sync"] is True,
          str({k: v for k, v in rep.items() if k != "keys"})[:200])
    check("i18n: yangi tugma kalitlari 3 tilda",
          all(channels_queue_t("cq_ch_btn_dna", lg) for lg in LANGS)
          and all(channels_queue_t("cq_ch_btn_best_time", lg) for lg in LANGS))

    # --- AI orkestrator: DNA system promptga ulanadi (faqat egasi kanalga) ---
    profile = {
        "channel_id": CH_ID, "average_post_length": 450, "avg_post_length": 450,
        "emoji_level": "medium", "cta_style": "always",
        "formatting_style": "media_rich", "top_topics": [],
        "confidence": 70, "confidence_score": 70, "sample_size": 12,
        "updated_at": "",
    }

    def _run_orch():
        async def go():
            results = {}
            # 1) EGASI kanal — DNA ulanadi
            prov = _CapturingProvider()
            fb_owner = _FakeDBModule(owner=USER_ID, profile=profile)
            r1 = await AIOrchestrator(
                provider_chain=ProviderChain(providers=[prov])
            ).orchestrate(
                user_id=USER_ID, prompt="Post yoz", lang="uz",
                context={"channel_id": CH_ID, "system_prompt": "BASE_PROMPT_MARKER",
                         "skip_quota": True, "skip_queue": True},
                db_module=fb_owner,
            )
            results["owner"] = (r1, prov.seen_ctx)

            # 2) BEGONA kanal — DNA ulanmaydi (IDOR)
            prov2 = _CapturingProvider()
            fb_foreign = _FakeDBModule(owner=OTHER_USER_ID, profile=profile)
            r2 = await AIOrchestrator(
                provider_chain=ProviderChain(providers=[prov2])
            ).orchestrate(
                user_id=USER_ID, prompt="Post yoz", lang="uz",
                context={"channel_id": CH_ID, "system_prompt": "BASE_PROMPT_MARKER",
                         "skip_quota": True, "skip_queue": True},
                db_module=fb_foreign,
            )
            results["foreign"] = (r2, prov2.seen_ctx)

            # 3) Kam ma'lumotli profil (sample 3) — DNA ulanmaydi
            thin = dict(profile, sample_size=3, confidence_score=0)
            prov3 = _CapturingProvider()
            fb_thin = _FakeDBModule(owner=USER_ID, profile=thin)
            r3 = await AIOrchestrator(
                provider_chain=ProviderChain(providers=[prov3])
            ).orchestrate(
                user_id=USER_ID, prompt="Post yoz", lang="uz",
                context={"channel_id": CH_ID, "system_prompt": "BASE_PROMPT_MARKER",
                         "skip_quota": True, "skip_queue": True},
                db_module=fb_thin,
            )
            results["thin"] = (r3, prov3.seen_ctx)

            # 4) channel_id'siz — DNA ulanmaydi
            prov4 = _CapturingProvider()
            r4 = await AIOrchestrator(
                provider_chain=ProviderChain(providers=[prov4])
            ).orchestrate(
                user_id=USER_ID, prompt="Post yoz", lang="uz",
                context={"system_prompt": "BASE_PROMPT_MARKER",
                         "skip_quota": True, "skip_queue": True},
                db_module=fb_owner,
            )
            results["no_channel"] = (r4, prov4.seen_ctx)
            return results
        return go()

    results = _with_db(FakeChannelStore(), _run_orch)
    for key in ("owner", "foreign", "thin", "no_channel"):
        r, ctx = results[key]
        check(f"orchestrator[{key}]: generatsiya muvaffaqiyatli", r.success is True,
              str(getattr(r, "error_code", None)))
    sp_owner = results["owner"][1].get("system_prompt", "")
    sp_foreign = results["foreign"][1].get("system_prompt", "")
    sp_thin = results["thin"][1].get("system_prompt", "")
    sp_noch = results["no_channel"][1].get("system_prompt", "")
    check("orchestrator[owner]: BASE prompt saqlandi",
          "BASE_PROMPT_MARKER" in sp_owner, sp_owner[:160])
    check("orchestrator[owner]: DNA bloki ulandi",
          "KANAL USLUBI (DNA)" in sp_owner and "450 belgi" in sp_owner, sp_owner[:200])
    check("orchestrator[owner]: channel_dna_attached flag",
          results["owner"][1].get("channel_dna_attached") is True)
    check("orchestrator[foreign]: DNA ulanmadi (IDOR)",
          "KANAL USLUBI (DNA)" not in sp_foreign, sp_foreign[:160])
    check("orchestrator[thin]: kam ma'lumot — DNA ulanmadi",
          "KANAL USLUBI (DNA)" not in sp_thin, sp_thin[:160])
    check("orchestrator[no_channel]: channel_id'siz — DNA ulanmadi",
          "KANAL USLUBI (DNA)" not in sp_noch, sp_noch[:160])


# ---------------------------------------------------------------------------
# TEST 8 — 📡 REAL-TIME INGESTION: on_channel_post → channel_post_events
# ---------------------------------------------------------------------------
def test_realtime_ingest_through_handler():
    print("\n== TEST 8: 📡 on_channel_post → event ingestion (asinxron, idempotent) ==")
    store = FakeChannelStore()
    store.owners[CH_ID] = USER_ID

    def _run():
        async def go():
            # 1) Yangi post
            upd = _channel_post_update(90001, "Yangi post matni buyurtma bering 🔥")
            await CH.on_channel_post(upd, _ctx("uz"))
            await asyncio.sleep(0.1)  # background task uchun kuzatish
            # 2) Xuddi shu post TAHRIRLANDI (ayni (channel_id, message_id) —
            # duplicate: ON CONFLICT DO NOTHING bilan qayta yozilmaydi)
            upd2 = _channel_post_update(90001, "Yangi post matni TAYYOR VERSIYA")
            await CH.on_channel_post(upd2, _ctx("uz"))
            await asyncio.sleep(0.1)
            # 3) Boshqa post
            upd3 = _channel_post_update(90002, "Ikkinchi post")
            await CH.on_channel_post(upd3, _ctx("uz"))
            await asyncio.sleep(0.1)
            return None
        return go()

    _with_db(store, _run)
    check("history: 3 ta post saqlandi (save_channel_post_history)",
          len(store.history) == 3, str(len(store.history)))
    keys = set(store.events.keys())
    check("events: yangi post yozildi (90001)", (CH_ID, 90001) in keys, str(keys))
    check("events: boshqa post yozildi (90002)", (CH_ID, 90002) in keys, str(keys))
    check("events: TAHRIRLANGAN post duplicate YO'Q (aynan 2 qator)",
          len(store.events) == 2, str(len(store.events)))
    row = store.events.get((CH_ID, 90001)) or {}
    check("event: metama'lumot saqlandi (soat 19, media, CTA)",
          row.get("post_hour") == 19 and row.get("has_media") is True
          and row.get("cta_detected") is True and row.get("media_type") == "photo",
          str(row))
    check("event: media file_id saqlandi (fayl mazmuni emas)",
          bool(row.get("media_file_id")), str(row.get("media_file_id")))


# ===========================================================================
def main():
    print("=" * 70)
    print(" 🧪 PHASE B — CHANNEL INTELLIGENCE (DNA + BEST TIME + MONITORING)")
    print("=" * 70)
    test_monitoring_metadata_extraction()
    test_event_idempotency()
    test_insufficient_data()
    test_dna_sufficient_data()
    test_best_time_generator()
    test_idor_protection()
    test_ui_and_integration()
    test_realtime_ingest_through_handler()

    print("\n" + "=" * 70)
    print(f" JAMI: o'tdi={PASSED}, xato={FAILURES}")
    if FAILURES:
        print(" [FAIL] CHANNEL INTELLIGENCE TESTDA XATOLIKLAR BOR ^^^")
        return 1
    print(" PHASE B CHANNEL INTELLIGENCE — 100% YASHIL ✔")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
