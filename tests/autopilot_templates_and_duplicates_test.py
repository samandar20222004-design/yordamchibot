#!/usr/bin/env python3
"""🚀📋🔁 PHASE C — AI AUTOPILOT + POST SHABLONLARI + DUBLIKAT DETEKTOR TEST.

Qamrov (topshiriq spetsifikatsiyasi bilan birma-bir — 7, 9, 10-bandlar):

  TEST 1:  🚀 7-KUNLIK REJA — pure shakllanish: normalize_ai_plan (7 kun
           qat'iy, kam/yaroqsiz → bo'sh), build_week_plan (Dushanba→
           Yakshanba, aniq vaqt, post matni + CTA), resolve_post_hour
           (best-time yoki standart), compose_post_text.
  TEST 2:  🧠 DNA + BEST TIME INTEGRATSIYASI — create_autopilot_plan kanal
           egaligi (IDOR) va Channel DNA/Smart Best Time tavsiyalariga
           tayanadi; AI javobi yomon bo'lsa yarim-yorti reja YO'Q.
  TEST 3:  🔒 NAVBAT LIMITI — FREE foydalanuvchi uchun 7 ta postga joy
           yetmasa ruxsat BERILMAYDI (fail-closed, DB xatosida ham).
  TEST 4:  ⚛️ ATOMIK YOZILISH — 7 ta post BITTA tranzaksiyada
           scheduled_posts navbatiga (real database.schedule_week_posts +
           fake cursor): muvaffaqiyatda 7 qator; o'rtada xato bo'lsa
           ROLLBACK — yarim-yorti navbat QOLMAYDI.
  TEST 5:  🎛 AUTOPILOT HANDLER OQIMI — mavzu → reja → tasdiqlash oynasi
           (4 tugma), limit ogohlantirishi, dublikat ogohlantirishi
           (3 tugma: [🚀 Baribir chiqarish] [✨ AI bilan yangilash]
           [❌ Bekor qilish]), muvaffaqiyatli atomik navbat, tahrirlash.
  TEST 6:  📋 SHABLON O'ZGARUVCHILARI — {TITLE} {TEXT} {PRICE} {LINK}
           {CTA} {SOURCE} {DATE} aniq almashtirilishi (registrga
           bog'liq emas, {DATE} avtomatik, noma'lum qavs saqlanadi).
  TEST 7:  🗃 post_templates DB QATLAMI — create/get/delete real
           database funksiyalari orqali (fake cursor).
  TEST 8:  🎛 SHABLON HANDLER OQIMI — menyusi (3 amal + Orqaga), yangi
           shablon, ishlatish → render → TO'G'RIDAN-TO'G'RI manual
           preview paneliga o'tish, o'chirish.
  TEST 9:  🔁 DUBLIKAT DETEKTORI (PURE) — 85%+ o'xshash matnda
           ogohlantirish (⚠️ "O'xshash post topildi..."), o'xshamagan
           matnda yo'q; AI modeli CHAQIRILMAYDI (yengil Jaccard/token
           overlap); screen_post_for_duplicates IDOR (FORBIDDEN) va
           fail-soft.
  TEST 10: 🔁 INTEGRATSIYA — autopilot rejalashtirishidan oldin va oddiy
           post chiqarilishidan oldin dublikat tekshiruvi: ogohlantirish
           chiqadi va hech narsa YOZILMAYDI; [🚀 Baribir chiqarish] bilan
           o'tkazib yuborish mumkin.
  TEST 11: 🔐 IDOR HIMOYASI — boshqa foydalanuvchining shablonini
           ko'rish/ishlatish/o'chirish MUMKIN EMAS (SQL darajasida
           WHERE user_id; handler darajasida "topilmadi" ekrani).
  TEST 12: 🧱 SXEMA/UI/ROUTING — post_templates jadvali schema.sql +
           database.py parallel (EXPECTED_TABLES/indeks hisobi), kanal
           panelida [🚀 AI Avtopilot] [📋 Shablonlar] (uz/ru/en, ≤64 bayt),
           callback routing va FSM holatlarining unikalligi.

Ishga tushirish:
    PYTHON=/tmp/venv/bin/python bash tests/run_tests.sh   # runner bosqichi
    python3 tests/autopilot_templates_and_duplicates_test.py
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
os.environ.setdefault("BOT_TOKEN", "123456:PHASE_C_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10077")
os.environ.setdefault("ENVIRONMENT", "test")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

import pytz  # noqa: E402

import database as db_mod  # noqa: E402
import handlers as H  # noqa: E402
import handlers.autopilot as AP  # noqa: E402
import handlers.templates as TP  # noqa: E402
import handlers.manual_post as MP  # noqa: E402
from keyboards.callback_data import (  # noqa: E402
    CALLBACK_DATA_MAX_BYTES, CB_CHANNEL_AUTOPILOT, CB_CHANNEL_TEMPLATES,
    CB_CHANNEL_BACK, CB_CHANNEL_DNA, CB_CHANNEL_BEST_TIME,
    callback_byte_len,
)
from keyboards.inline import (  # noqa: E402
    get_duplicate_warning_keyboard, get_manual_post_panel,
    render_channel_panel,
)
from services.autopilot.planner import (  # noqa: E402
    AUTOPILOT_DAYS, DEFAULT_POST_HOUR, build_week_plan, check_week_quota,
    compose_post_text, create_autopilot_plan, normalize_ai_plan,
    resolve_post_hour, schedule_autopilot_week,
)
from services.channels.duplicate_detector import (  # noqa: E402
    DUPLICATE_THRESHOLD, DUPLICATE_WARNING_MESSAGE, check_duplicate,
    containment_ratio, jaccard_similarity, normalize_text,
    screen_post_for_duplicates, tokenize,
)
from services.templates.service import (  # noqa: E402
    TEMPLATE_VARIABLES, extract_variables, parse_variable_values,
    render_template, validate_template_content,
)
from translations import (  # noqa: E402
    autopilot_parity_report, channels_queue_t,
    manual_post_parity_report, templates_parity_report,
)

TZ = pytz.timezone("Asia/Tashkent")
UTC = pytz.utc


def _now():
    """Test reference vaqti (tz-aware): 2026-09-17 12:00 Toshkent (Payshanba)."""
    return TZ.localize(datetime(2026, 9, 17, 12, 0, 0))

USER_ID = 888001          # kanal EGASI
OTHER_USER_ID = 888999    # begona (IDOR)
CH_ID = "-1007771234567"
CH_TITLE = "Phase C test kanali"
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
class FakeStore:
    """post_templates + scheduled_posts + channel intelligence + tarix mock."""

    def __init__(self):
        self.templates = {}        # id -> dict(user_id, name, content, variables)
        self._next_tpl_id = 100
        self.posts = []            # scheduled_posts qatorlari (dict) — COMMIT'dan keyin
        self._txn_posts = []       # faol tranzaksiya buferi (ROLLBACK'da tashlanadi)
        self._next_post_id = 1
        self._next_post_number = 0
        self.events = {}           # (channel_id, message_id) -> event dict
        self.owners = {}           # channel_id -> user_id
        self.channels = {}         # channel_id -> (id, title, tone)
        self.plans = {USER_ID: "free", OTHER_USER_ID: "free"}
        self.history = {}          # channel_id -> [content, ...] (yangisi birinchi)
        self.fail_insert_at = None  # N-chi INSERT'da portlash (atomiklik testi)
        self._insert_counter = 0
        self.commits = 0
        self.rollbacks = 0
        self.check_queue_error = False
        self.calls = []            # (funksiya nomi, args, kwargs)

    # -- SQL emulyatsiyasi ---------------------------------------------------
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
            st = self._store

            if "PG_ADVISORY_XACT_LOCK" in su:
                return

            if "INSERT INTO POST_TEMPLATES" in su:
                uid, ch_id, name, content, variables_json = params
                if len([t for t in st.templates.values()
                        if t["user_id"] == int(uid)]) >= db_mod.POST_TEMPLATES_LIMIT:
                    raise Exception("limit reached")
                st._next_tpl_id += 1
                row = {
                    "id": st._next_tpl_id, "user_id": int(uid),
                    "channel_id": ch_id, "name": name, "content": content,
                    "variables": variables_json,
                }
                st.templates[row["id"]] = row
                self.rowcount = 1
                self._rows = [(row["id"],)]
                return

            if "SELECT COUNT(*) FROM POST_TEMPLATES" in su:
                uid = int(params[0])
                count = len([t for t in st.templates.values()
                             if t["user_id"] == uid])
                self._rows = [(count,)]
                return

            if "FROM POST_TEMPLATES" in su and su.startswith("SELECT"):
                if "COUNT" in su:
                    return
                rows = [t for t in st.templates.values()
                        if t["user_id"] == int(params[0])]
                if "WHERE ID = %S AND USER_ID" in su:
                    # Bitta shablon: WHERE id = %s AND user_id = %s (IDOR).
                    tid = int(params[0])
                    rows = [t for t in st.templates.values()
                            if t["id"] == tid and t["user_id"] == int(params[1])]
                if "ORDER BY CREATED_AT" in su:
                    rows = sorted(rows, key=lambda t: t["id"], reverse=True)
                limit = int(params[-1]) if params and str(params[-1]).isdigit() else 50
                self._rows = [
                    (t["id"], t["user_id"], t["channel_id"], t["name"],
                     t["content"], t["variables"], None)
                    for t in rows[:limit]
                ]
                return

            if "DELETE FROM POST_TEMPLATES" in su:
                tid, uid = int(params[0]), int(params[1])
                target = st.templates.get(tid)
                if target is not None and target["user_id"] == uid:
                    del st.templates[tid]
                    self.rowcount = 1
                return

            if "INSERT INTO SCHEDULED_POSTS" in su:
                st._insert_counter += 1
                if (st.fail_insert_at is not None
                        and st._insert_counter >= st.fail_insert_at):
                    raise Exception("boom: simulated mid-transaction failure")
                st._next_post_id += 1
                if "INLINE_BUTTON_TEXT" in su:
                    # add_post shakli (16 param): scheduled_time=%s[10],
                    # user_post_number=%s[11].
                    uid, ch_id, content = params[0], params[1], params[3]
                    scheduled_time, post_number = params[10], params[11]
                else:
                    # schedule_week_posts shakli (6 param).
                    uid, ch_id, content = params[0], params[1], params[3]
                    scheduled_time, post_number = params[4], params[5]
                # TRANZAKSIYA BUFERIGA yozamiz — commit'dan keyingina ko'rinadi
                # (rollback'da butunlay yo'qoladi: atomiklik semantikasi).
                st._txn_posts.append({
                    "id": st._next_post_id, "user_id": int(uid),
                    "channel_id": str(ch_id), "content": content,
                    "scheduled_time": scheduled_time, "status": "pending",
                    "user_post_number": post_number,
                })
                self.rowcount = 1
                self._rows = [(st._next_post_id,)]
                return

            if "MAX(USER_POST_NUMBER)" in su:
                uid = int(params[0])
                # Tranzaksiya ichida o'z INSERT'larimiz ham ko'rinadi.
                nums = [p["user_post_number"] for p in st.posts
                        if p["user_id"] == uid]
                nums += [p["user_post_number"] for p in st._txn_posts
                         if p["user_id"] == uid]
                self._rows = [(max(nums) if nums else 0,)]
                return

            if "FROM CHANNEL_POST_EVENTS" in su and su.startswith("SELECT"):
                ch_id, limit = str(params[0]), int(params[1])
                rows = [r for (c, _m), r in st.events.items() if c == ch_id]
                rows.sort(key=lambda r: r["message_id"], reverse=True)
                # Real SELECT ustun tartibi (10 ustun, media_file_id YO'Q):
                # (channel_id, message_id, post_hour, post_weekday, has_media,
                #  media_type, length, cta_detected, emoji_density, created_at)
                self._rows = [
                    (r["channel_id"], r["message_id"], r["post_hour"],
                     r["post_weekday"], r["has_media"], r["media_type"],
                     r["length"], r["cta_detected"], r["emoji_density"],
                     datetime(2026, 9, 1, r["post_hour"], 0, 0))
                    for r in rows[:limit]
                ]
                return

            if "INSERT INTO CHANNEL_INTELLIGENCE_PROFILES" in su:
                ch_id = str(params[0])
                st.profiles_saved = st.profiles_saved if hasattr(st, "profiles_saved") else {}
                st.profiles_saved[ch_id] = True
                self.rowcount = 1
                return

            if "FROM CHANNEL_INTELLIGENCE_PROFILES" in su and su.startswith("SELECT"):
                self._rows = []  # profil testida DNA hisoblanadi (saqlanmagan)
                return

            if "FROM CHANNELS" in su and su.startswith("SELECT"):
                owner = st.owners.get(str(params[0]))
                self._rows = [(owner,)] if owner is not None else []
                return

            if "FROM CHANNEL_POSTS_HISTORY" in su and su.startswith("SELECT"):
                ch_id, limit = str(params[0]), int(params[1])
                texts = st.history.get(ch_id, [])[:limit]
                now = datetime(2026, 9, 16, 12, 0, 0)
                self._rows = [
                    (1000 + i, ch_id, 500 + i, text, 100, now, now)
                    for i, text in enumerate(texts)
                ]
                return

            if "PLAN_TYPE" in su and "FROM USERS" in su:
                uid = int(params[0])
                self._rows = [(st.plans.get(uid, "free"),)]
                return

            if "COUNT(*) FROM SCHEDULED_POSTS" in su:
                uid = int(params[0])
                count = len([p for p in st.posts
                             if p["user_id"] == uid and p["status"] == "pending"])
                self._rows = [(count,)]
                return

            # check_queue_limit xatolik simulyatsiyasi (fail-closed test)
            if st.check_queue_error and "PLAN_TYPE" not in su:
                raise Exception("db down")

        def fetchone(self):
            return self._rows[0] if self._rows else None

        def fetchall(self):
            return list(self._rows)

    def db_cursor(self, commit: bool = False):
        @contextmanager
        def _cm():
            # Yangi tranzaksiya: bufer toza (nested chaqiruvlar uchun ham).
            outer_txn = self._txn_posts
            self._txn_posts = []
            cur = self.Cursor(self)
            try:
                yield cur
            except Exception:
                self.rollbacks += 1
                self._txn_posts = outer_txn  # ROLLBACK: bufer tashlanadi
                raise
            else:
                if commit:
                    self.commits += 1
                    # COMMIT: tranzaksiya qatorlari ko'rinadigan bo'ladi.
                    outer_txn.extend(self._txn_posts)
                    self.posts.extend(self._txn_posts)
                self._txn_posts = outer_txn
        return _cm()

    # -- run_db dispatcher (asinxron) ---------------------------------------
    async def run_db(self, fn, *args, **kwargs):
        name = getattr(fn, "__name__", str(fn))
        self.calls.append((name, args, tuple(sorted(kwargs.items()))))
        if name == "check_queue_limit" and self.check_queue_error:
            raise Exception("db down")
        if name == "get_user_channels_with_tone":
            uid = args[0]
            if uid == USER_ID and CH_ID in self.channels:
                return [(CH_ID, CH_TITLE, "friendly")]
            return []
        # Qolganlari — HAQIQIY database funksiyalari (patch'langan cursor
        # orqali): SQL mantig'i va IDOR filtrlari production kodi bilan
        # sinanadi.
        return await asyncio.to_thread(fn, *args, **kwargs)


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


def make_events(count=24, hour_peak=19, hour_other=18, length=450,
                emoji_density=0.009):
    """Deterministik channel_post_events (DNA + best time uchun yetarli)."""
    events = []
    for i in range(count):
        events.append({
            "channel_id": CH_ID,
            "message_id": 9000 + i,
            "post_hour": hour_peak if i < 16 else hour_other,
            "post_weekday": i % 7,
            "has_media": i < 14,
            "media_type": "photo" if i < 14 else None,
            "media_file_id": "f" if i < 14 else None,
            "length": length,
            "cta_detected": True,
            "emoji_density": emoji_density,
        })
    return events


def default_store():
    """Egasi USER_ID bo'lgan kanal + 24 ta event bilan standart store."""
    store = FakeStore()
    store.owners[CH_ID] = USER_ID
    store.channels[CH_ID] = (CH_ID, CH_TITLE, "friendly")
    for ev in make_events():
        store.events[(ev["channel_id"], ev["message_id"])] = ev
    return store


# ---------------------------------------------------------------------------
# YORDAMCHILAR — Update/Query fakeri (tarmoqqa chiqmaydi)
# ---------------------------------------------------------------------------
class _Msg:
    def __init__(self, user_id=USER_ID, text=""):
        self.from_user = SimpleNamespace(id=user_id, first_name="Tester")
        self.chat = SimpleNamespace(id=user_id, type="private")
        self.text = text
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


def _upd_msg(msg, user_id=USER_ID):
    return SimpleNamespace(message=msg, effective_message=msg,
                           effective_user=SimpleNamespace(id=user_id,
                                                          first_name="Tester"),
                           callback_query=None)


def _ctx(lang="uz"):
    return SimpleNamespace(user_data={"lang": lang}, chat_data={},
                           bot=SimpleNamespace(username="phase_c_test_bot"),
                           application=None)


def _cbs(markup):
    rows = getattr(markup, "inline_keyboard", None)
    return [b.callback_data for row in rows for b in row] if rows else []


def _labels(markup):
    rows = getattr(markup, "inline_keyboard", None)
    return [b.text for row in rows for b in row] if rows else []


AI_PLAN = [
    {"topic": f"Kun mavzusi {i + 1}", "format": "e'lon",
     "content": f"🔥 <b>{i + 1}-kun posti</b>\n\nBu {i + 1}-kun uchun tayyor "
                f"post matni — mahsulot va foyda tavsifi bilan.",
     "cta": "👉 Buyurtma bering: @shop"}
    for i in range(7)
]


async def _fake_generate(topic, lang="uz", dna_block="", best_hour=None, days=7):
    """AI o'rnini bosuvchi deterministik generator (tarmoqsiz)."""
    assert "KANAL USLUBI" in dna_block or dna_block == "", dna_block
    return normalize_ai_plan({"days": AI_PLAN}, days)


# ---------------------------------------------------------------------------
# TEST 1 — 🚀 7 kunlik rejaning PURE shakllanishi
# ---------------------------------------------------------------------------
def test_week_plan_formation():
    print("\n== TEST 1: 🚀 7 kunlik reja — pure shakllanish ==")

    check("AUTOPILOT_DAYS = 7", AUTOPILOT_DAYS == 7)
    check("standart soat 19", DEFAULT_POST_HOUR == 19)

    # --- normalize_ai_plan: qat'iy 7 kun ---
    normalized = normalize_ai_plan({"days": AI_PLAN}, 7)
    check("AI rejasi normalizatsiya: 7 kun", len(normalized) == 7,
          str(len(normalized)))
    check("har kunda content + cta bor",
          all(d["content"] and d["cta"] for d in normalized))
    check("6 kunlik AI javobi QAT'IYAN RAD (yarim-yorti yo'q)",
          normalize_ai_plan({"days": AI_PLAN[:6]}, 7) == [])
    check("matnsiz kun RAD",
          normalize_ai_plan({"days": AI_PLAN[:6] + [{"topic": "x"}]}, 7) == [])
    check("dict bo'lmagan javob RAD", normalize_ai_plan(["a", "b"], 7) == [])

    # --- build_week_plan: Dushanba → Yakshanba, aniq vaqt ---
    now = _now()  # Payshanba, 2026-09-17
    days = build_week_plan(normalized, hour=19, now=now)
    check("7 kun yig'ildi", len(days) == 7, str(len(days)))
    check("hafta kuni ketma-ketligi Dushanba→Yakshanba",
          [d["weekday"] for d in days] == [0, 1, 2, 3, 4, 5, 6],
          str([d["weekday"] for d in days]))
    check("birinchi kun 21.09 (2026, Dushanba)", days[0]["date"] == "21.09",
          days[0]["date"])
    check("oxirgi kun 27.09 (Yakshanba)", days[6]["date"] == "27.09",
          days[6]["date"])
    check("aniq vaqt: 19:00 (best time bo'yicha)",
          all(d["time"] == "19:00" for d in days),
          str([d["time"] for d in days]))
    check("vaqtlar kelajakda (o'tmishga tushmaydi)",
          all(d["scheduled_time"] > now for d in days))
    check("post matni: content + CTA birlashgan",
          days[0]["post_text"].endswith("👉 Buyurtma bering: @shop"),
          days[0]["post_text"][-40:])
    check("kunlar bir-biridan farq qiladi (dublikat kun yo'q)",
          len({d["post_text"] for d in days}) == 7)

    # --- resolve_post_hour: soxta raqamlar uydirmaslik ---
    check("best time insufficient → standart 19",
          resolve_post_hour({"insufficient": True, "peak_hour": None}) == 19)
    check("peak_hour=21 → 21", resolve_post_hour({"peak_hour": 21}) == 21)
    check("buzilgan peak → standart", resolve_post_hour({"peak_hour": "x"}) == 19)

    # --- compose_post_text ---
    check("CTA qo'shiladi",
          compose_post_text("Matn", "CTA") == "Matn\n\nCTA")
    check("CTA matnda bo'lsa takrorlanmaydi",
          compose_post_text("Matn CTA", "cta") == "Matn CTA")
    check("bo'sh CTA — matn o'zi",
          compose_post_text("Matn", "") == "Matn")


# ---------------------------------------------------------------------------
# TEST 2 — 🧠 create_autopilot_plan: DNA + Best Time + IDOR
# ---------------------------------------------------------------------------
def test_create_plan_service():
    print("\n== TEST 2: 🧠 create_autopilot_plan — DNA + Best Time + IDOR ==")
    import services.autopilot.planner as planner

    store = default_store()
    original = planner.generate_autopilot_week
    planner.generate_autopilot_week = _fake_generate
    try:
        result = _with_db(store, lambda: create_autopilot_plan(
            USER_ID, CH_ID, "Kofeynya yangi menyusi", "uz"))
    finally:
        planner.generate_autopilot_week = original

    check("reja tuzildi (ok=True)", result.get("ok") is True, str(result))
    days = result.get("days") or []
    check("7 kun", len(days) == 7, str(len(days)))
    check("soat best-time statistikasidan (peak 19)",
          result.get("hour") == 19 and result.get("hour_source") == "best_time",
          str((result.get("hour"), result.get("hour_source"))))
    check("tavsiya oynasi kelgan",
          result.get("best_window") == "19:00 - 21:00",
          str(result.get("best_window")))
    check("Channel DNA promptiga ulangan (dna_attached)",
          result.get("dna_attached") is True, str(result.get("dna_attached")))
    check("har kun: aniq vaqt + mavzu + format + matn + CTA",
          all(d["time"] and d["topic"] and d["format"]
              and d["post_text"] for d in days))

    # --- IDOR: begona foydalanuvchining kanaliga reja YO'Q ---
    store2 = default_store()
    planner.generate_autopilot_week = _fake_generate
    try:
        forbidden = _with_db(store2, lambda: create_autopilot_plan(
            OTHER_USER_ID, CH_ID, "Begona mavzu", "uz"))
    finally:
        planner.generate_autopilot_week = original
    check("IDOR: begona uchun FORBIDDEN",
          forbidden.get("ok") is False
          and forbidden.get("error_code") == "FORBIDDEN", str(forbidden))

    # --- AI yiqilsa: yarim-yorti reza YO'Q ---
    store3 = default_store()
    planner.generate_autopilot_week = _fake_generate
    try:
        async def _failing_generate(*args, **kwargs):
            return []
        planner.generate_autopilot_week = _failing_generate
        failed = _with_db(store3, lambda: create_autopilot_plan(
            USER_ID, CH_ID, "Mavzu", "uz"))
    finally:
        planner.generate_autopilot_week = original
    check("AI yiqilsa: ok=False AI_FAILED (soxta reja yo'q)",
          failed.get("ok") is False and failed.get("error_code") == "AI_FAILED",
          str(failed))

    check("juda qisqa mavzu rad etiladi",
          create_autopilot_plan_sync_short())

    # --- kam ma'lumotli kanal: best time yetarli emas → standart soat ---
    store4 = FakeStore()
    store4.owners[CH_ID] = USER_ID
    store4.channels[CH_ID] = (CH_ID, CH_TITLE, "friendly")
    for ev in make_events(3):  # < 5 post
        store4.events[(ev["channel_id"], ev["message_id"])] = ev
    planner.generate_autopilot_week = _fake_generate
    try:
        weak = _with_db(store4, lambda: create_autopilot_plan(
            USER_ID, CH_ID, "Mavzu", "uz"))
    finally:
        planner.generate_autopilot_week = original
    check("kam ma'lumot: baribir reja, lekin standart soat + ochiq aytilgan",
          weak.get("ok") is True and weak.get("hour_source") == "default",
          str((weak.get("ok"), weak.get("hour_source"))))


def create_autopilot_plan_sync_short():
    """Qisqa mavzu — sinxron tekshiruv (AI/DB'siz rad etilishi kerak)."""
    result = asyncio.run(create_autopilot_plan(USER_ID, CH_ID, "ab", "uz"))
    return result.get("ok") is False and result.get("error_code") == "INVALID_TOPIC"


# ---------------------------------------------------------------------------
# TEST 3 — 🔒 Navbat limiti (FREE qat'iy nazorat)
# ---------------------------------------------------------------------------
def test_quota_control():
    print("\n== TEST 3: 🔒 Navbat limiti — FREE uchun qat'iy nazorat ==")

    class _QuotaDB:
        def __init__(self, can_add, current, max_q, error=False):
            self._r = (can_add, current, max_q)
            self.error = error

        def check_queue_limit(self, user_id):
            if self.error:
                raise Exception("db down")
            return self._r

        async def run_db(self, fn, *args, **kwargs):
            return fn(*args, **kwargs)

    # FREE: 3/5 band — 7 ta postga joy YO'Q.
    r = asyncio.run(check_week_quota(USER_ID, 7, db_module=_QuotaDB(True, 3, 5)))
    check("FREE 3/5: ruxsat YO'Q", r["allowed"] is False, str(r))
    check("free_slots aniq hisoblangan", r["free_slots"] == 2, str(r))

    # PRO: 0/999 — joy bor.
    r2 = asyncio.run(check_week_quota(USER_ID, 7, db_module=_QuotaDB(True, 0, 999)))
    check("PRO 0/999: ruxsat bor", r2["allowed"] is True, str(r2))

    # DB xatosi — FAIL-CLOSED.
    r3 = asyncio.run(check_week_quota(USER_ID, 7,
                                      db_module=_QuotaDB(True, 0, 999, error=True)))
    check("DB xatosi: fail-closed (ruxsat yo'q)", r3["allowed"] is False, str(r3))

    # REAL check_queue_limit + fake cursor: free plan, 4 pending → 4+7 > 5.
    store = default_store()
    store.plans[USER_ID] = "free"
    for i in range(4):
        store.posts.append({"id": 900 + i, "user_id": USER_ID,
                            "channel_id": CH_ID, "content": f"p{i}",
                            "scheduled_time": datetime(2026, 9, 20 + i),
                            "status": "pending", "user_post_number": i + 1})
    real = _with_db(store, lambda: check_week_quota(USER_ID, 7))
    check("real check_queue_limit: FREE 4/5 → 7 postga ruxsat YO'Q",
          real["allowed"] is False and real["current"] == 4 and real["max"] == 5,
          str(real))


# ---------------------------------------------------------------------------
# TEST 4 — ⚛️ ATOMIK yozilish (real schedule_week_posts + fake cursor)
# ---------------------------------------------------------------------------
def test_atomic_scheduling():
    print("\n== TEST 4: ⚛️ 7 post BITTA tranzaksiyada (atomik) ==")

    now = datetime(2026, 9, 17, 12, 0, 0)
    days = build_week_plan(normalize_ai_plan({"days": AI_PLAN}, 7),
                           hour=19, now=now)

    # --- muvaffaqiyat: 7 qator, BITTA commit ---
    store = default_store()
    result = _with_db(store, lambda: schedule_autopilot_week(
        USER_ID, CH_ID, days))
    check("success=True", result.get("success") is True, str(result))
    check("count=7", result.get("count") == 7, str(result.get("count")))
    check("7 ta id qaytdi", len(result.get("ids") or []) == 7)
    check("navbatda FAQAT 7 qator (pending)", len(store.posts) == 7
          and all(p["status"] == "pending" for p in store.posts))
    check("BITTA commit (bitta tranzaksiya)", store.commits == 1,
          str(store.commits))
    check("rollback yo'q", store.rollbacks == 0, str(store.rollbacks))
    times = [p["scheduled_time"] for p in store.posts]
    check("vaqtlar Dushanba→Yakshanba tartibida",
          [t.weekday() for t in times] == [0, 1, 2, 3, 4, 5, 6])
    check("post raqamlari tartibda va unikal",
          [p["user_post_number"] for p in store.posts] == [1, 2, 3, 4, 5, 6, 7])

    # --- o'rtada xato: ROLLBACK — yarim-yorti navbat QOLMAYDI ---
    store2 = default_store()
    store2.fail_insert_at = 4  # 4-chi INSERT'da portlaydi
    result2 = _with_db(store2, lambda: schedule_autopilot_week(
        USER_ID, CH_ID, days))
    check("xatoda success=False", result2.get("success") is False, str(result2))
    check("ATOMIKLIK: bitta qator ham qolmadi (rollback)",
          len(store2.posts) == 0, str(len(store2.posts)))
    check("rollback qayd etildi", store2.rollbacks >= 1,
          str(store2.rollbacks))
    check("commit bo'lmadi", store2.commits == 0, str(store2.commits))

    # --- bo'sh ro'yxat ---
    store3 = default_store()
    result3 = _with_db(store3, lambda: schedule_autopilot_week(
        USER_ID, CH_ID, []))
    check("bo'sh reja → error=empty",
          result3.get("success") is False and result3.get("error") == "empty",
          str(result3))


# ---------------------------------------------------------------------------
# TEST 5 — 🎛 Autopilot handler oqimi
# ---------------------------------------------------------------------------
def test_autopilot_handler_flow():
    print("\n== TEST 5: 🎛 Autopilot handler — oqim, limit, dublikat, atomik ==")

    # --- 5.1 kirish: IDOR (begona kanal) ---
    store = default_store()
    q = _Query(f"{CB_CHANNEL_AUTOPILOT}{CH_ID}", user_id=OTHER_USER_ID)
    state = _with_db(store, lambda: AP.channel_autopilot_entry(
        _upd_query(q), _ctx("uz")))
    check("IDOR: begona kanal uchun kirish YO'Q (END)",
          state == ConversationEnd(), str(state))

    # --- 5.2 kirish: egasi → mavzu so'rovi ---
    q2 = _Query(f"{CB_CHANNEL_AUTOPILOT}{CH_ID}")
    state2 = _with_db(store, lambda: AP.channel_autopilot_entry(
        _upd_query(q2), _ctx("uz")))
    check("egasi: AUTOPILOT_TOPIC holati", state2 == AP.AUTOPILOT_TOPIC,
          str(state2))
    check("mavzu so'rovi ko'rsatildi",
          "mavzu" in q2.screen.get("text", "").lower()
          or "AI AVTOPILOT" in q2.screen.get("text", ""),
          q2.screen.get("text", "")[:80])

    # --- 5.3 mavzu → reja → tasdiqlash oynasi (4 tugma) ---
    plan_result = {
        "ok": True, "days": build_week_plan(
            normalize_ai_plan({"days": AI_PLAN}, 7), hour=19,
            now=_now()),
        "hour": 19, "hour_source": "best_time",
        "best_window": "19:00 - 21:00", "dna_attached": True,
    }
    original_plan = AP.create_autopilot_plan

    async def _plan_ok(*args, **kwargs):
        return plan_result

    AP.create_autopilot_plan = _plan_ok
    try:
        msg = _Msg(text="Kofeynya yangi menyusi")
        ctx = _ctx("uz")
        ctx.user_data[AP.UD_CHANNEL] = CH_ID
        ctx.user_data[AP.UD_TITLE] = CH_TITLE
        ctx.user_data[AP.UD_TOPIC] = "Kofeynya menyusi"
        state3 = _with_db(store, lambda: AP.autopilot_topic_received(
            _upd_msg(msg), ctx))
    finally:
        AP.create_autopilot_plan = original_plan
    check("reja: AUTOPILOT_VIEW holati", state3 == AP.AUTOPILOT_VIEW,
          str(state3))
    check("reja matni chiqdi (kunlar ko'rinadi)",
          any("Dushanba" in m["text"] for m in msg.sent), str(len(msg.sent)))
    confirm_kb = msg.sent[-1].get("reply_markup") if msg.sent else None
    check("tasdiqlash oynasi: 4 tugma SPEKS bo'yicha",
          _cbs(confirm_kb) == ["ap_confirm", "ap_edit", "ap_regen", "ap_cancel"],
          str(_cbs(confirm_kb)))
    check("SPEKS yorliqlari: Hammasini rejalashtirish/Tahrirlash/Qayta yaratish/Bekor qilish",
          _labels(confirm_kb) == ["🚀 Hammasini rejalashtirish", "✏️ Tahrirlash",
                                  "🔄 Qayta yaratish", "❌ Bekor qilish"],
          str(_labels(confirm_kb)))

    # --- 5.4 [🚀 Hammasini rejalashtirish]: FREE limit to'lgan ---
    store.plans[USER_ID] = "free"
    for i in range(3):
        store.posts.append({"id": 950 + i, "user_id": USER_ID,
                            "channel_id": CH_ID, "content": f"x{i}",
                            "scheduled_time": datetime(2026, 9, 20 + i),
                            "status": "pending", "user_post_number": 50 + i})
    q_confirm = _Query("ap_confirm")
    ctxq = _ctx("uz")
    ctxq.user_data[AP.UD_CHANNEL] = CH_ID
    ctxq.user_data[AP.UD_TITLE] = CH_TITLE
    ctxq.user_data[AP.UD_TOPIC] = "Kofeynya menyusi"
    ctxq.user_data[AP.UD_DAYS] = plan_result["days"]
    state4 = _with_db(store, lambda: AP.autopilot_confirm_callback(
        _upd_query(q_confirm), ctxq))
    check("limit: VIEW'da qoladi (yopilmaydi)", state4 == AP.AUTOPILOT_VIEW,
          str(state4))
    check("limit: xavfsiz ogohlantirish (Navbat limiti)",
          "Navbat limiti" in q_confirm.screen.get("text", ""),
          q_confirm.screen.get("text", "")[:80])
    check("limit: hech narsa yozilmadi", len(store.posts) == 3,
          str(len(store.posts)))
    check("limit: 💎 PRO taklifi chiqadi",
          "sub_open" in _cbs(q_confirm.screen.get("reply_markup")),
          str(_cbs(q_confirm.screen.get("reply_markup"))))

    # --- 5.5 limit oshib ketganda: [❌ Bekor qilish] toza yopadi ---
    q_cancel = _Query("ap_cancel")
    ctxc = _ctx("uz")
    ctxc.user_data[AP.UD_DAYS] = plan_result["days"]
    state5 = _with_db(store, lambda: AP.autopilot_cancel_callback(
        _upd_query(q_cancel), ctxc))
    check("bekor qilish: END + sessiya tozalandi",
          state5 == ConversationEnd() and not ctxc.user_data.get(AP.UD_DAYS),
          str(state5))

    # --- 5.6 dublikat: 85%+ o'xshash post mavjud → 3 tugmali ogohlantirish ---
    # (PRO plan — FREE limit (5 < 7) bloklab qo'ymasligi uchun)
    dup_store = default_store()
    dup_store.plans[USER_ID] = "pro"
    dup_history_text = AI_PLAN[0]["content"] + "\n\n👉 Buyurtma bering: @shop"
    dup_store.history[CH_ID] = [dup_history_text]
    ctxd = _ctx("uz")
    ctxd.user_data[AP.UD_CHANNEL] = CH_ID
    ctxd.user_data[AP.UD_TITLE] = CH_TITLE
    ctxd.user_data[AP.UD_TOPIC] = "Kofeynya menyusi"
    ctxd.user_data[AP.UD_DAYS] = plan_result["days"]
    q_dup = _Query("ap_confirm")
    state6 = _with_db(dup_store, lambda: AP.autopilot_confirm_callback(
        _upd_query(q_dup), ctxd))
    check("dublikat: VIEW'da qoladi (navbatga qo'yilmadi)",
          state6 == AP.AUTOPILOT_VIEW, str(state6))
    dup_text = q_dup.screen.get("text", "")
    check("dublikat: SPEKS ogohlantirish matni AYNAN",
          "⚠️ O'xshash post topildi. Bu post yaqindagi postingizga juda "
          "o'xshaydi." in dup_text, dup_text[:120])
    dup_cbs = _cbs(q_dup.screen.get("reply_markup"))
    check("dublikat: 3 tugma [🚀 Baribir chiqarish][✨ AI bilan yangilash][❌ Bekor qilish]",
          dup_cbs == ["ap_force", "ap_refresh", "ap_cancel"], str(dup_cbs))
    check("dublikat: ta'sirlangan kun ko'rsatilgan",
          "1-kun" in dup_text, dup_text[:200])
    check("dublikat: hech narsa rejalashtirilmadi",
          len(dup_store.posts) == 0, str(len(dup_store.posts)))

    # --- 5.7 [🚀 Baribir chiqarish]: dublikatga qaramay atomik navbat ---
    q_force = _Query("ap_force")
    state7 = _with_db(dup_store, lambda: AP.autopilot_force_callback(
        _upd_query(q_force), ctxd))
    check("force: END (yakuniy ekran)", state7 == ConversationEnd(), str(state7))
    check("force: 7 ta post BITTA tranzaksiyada yozildi",
          len(dup_store.posts) == 7 and dup_store.commits == 1,
          f"posts={len(dup_store.posts)} commits={dup_store.commits}")
    check("force: muvaffaqiyat matni (navbatga qo'yildi)",
          "navbatga qo'yildi" in q_force.screen.get("text", ""),
          q_force.screen.get("text", "")[:80])

    # --- 5.8 [✏️ Tahrirlash]: kun tanlash → yangi matn ---
    ctxe = _ctx("uz")
    ctxe.user_data[AP.UD_CHANNEL] = CH_ID
    ctxe.user_data[AP.UD_TITLE] = CH_TITLE
    ctxe.user_data[AP.UD_TOPIC] = "Kofeynya menyusi"
    ctxe.user_data[AP.UD_DAYS] = plan_result["days"]
    q_edit = _Query("ap_edit")
    state8 = _with_db(dup_store, lambda: AP.autopilot_edit_callback(
        _upd_query(q_edit), ctxe))
    check("tahrirlash: kun tanlash holati",
          state8 == AP.AUTOPILOT_EDIT_DAY, str(state8))
    edit_cbs = _cbs(q_edit.screen.get("reply_markup"))
    check("tahrirlash: 7 kun tugmasi + Orqaga + Bekor",
          len(edit_cbs) == 9 and edit_cbs[0] == "ap_eday:0"
          and edit_cbs[6] == "ap_eday:6", str(edit_cbs))

    q_day = _Query("ap_eday:2")
    state9 = _with_db(dup_store, lambda: AP.autopilot_edit_day_callback(
        _upd_query(q_day), ctxe))
    check("kun tanlandi: matn kutilmoqda",
          state9 == AP.AUTOPILOT_EDIT_INPUT, str(state9))

    msg2 = _Msg(text="🔥 TO'LIQ YANGI MATN — 3-kun uchun boshqacha post!")
    state10 = _with_db(dup_store, lambda: AP.autopilot_edit_input_received(
        _upd_msg(msg2), ctxe))
    check("yangi matn: VIEW'ga qaytdi", state10 == AP.AUTOPILOT_VIEW,
          str(state10))
    updated = ctxe.user_data[AP.UD_DAYS][2]["post_text"]
    check("3-kun posti yangilandi",
          "TO'LIQ YANGI MATN" in updated, updated[:60])

    # --- 5.9 toza reja: dublikatsiz → darhol atomik navbat ---
    clean_store = default_store()
    clean_store.plans[USER_ID] = "pro"
    clean_store.history[CH_ID] = ["Butunlay boshqa mavzudagi post — matcha "
                                  "latte taqdimoti haqida yangilik!"]
    ctxf = _ctx("uz")
    ctxf.user_data[AP.UD_CHANNEL] = CH_ID
    ctxf.user_data[AP.UD_TITLE] = CH_TITLE
    ctxf.user_data[AP.UD_TOPIC] = "Kofeynya menyusi"
    ctxf.user_data[AP.UD_DAYS] = plan_result["days"]
    q_clean = _Query("ap_confirm")
    state11 = _with_db(clean_store, lambda: AP.autopilot_confirm_callback(
        _upd_query(q_clean), ctxf))
    check("toza reja: END + 7 post yozildi",
          state11 == ConversationEnd() and len(clean_store.posts) == 7,
          f"state={state11} posts={len(clean_store.posts)}")
    check("toza reja: dublikat oynasi CHIQMADI",
          "O'xshash post topildi" not in q_clean.screen.get("text", ""),
          q_clean.screen.get("text", "")[:80])


def ConversationEnd():
    from telegram.ext import ConversationHandler
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# TEST 6 — 📋 Shablon o'zgaruvchilari (pure)
# ---------------------------------------------------------------------------
def test_template_variables():
    print("\n== TEST 6: 📋 Shablon o'zgaruvchilari — aniq almashtirish ==")

    check("7 ta o'zgaruvchi SPEKS bo'yicha",
          tuple(sorted(TEMPLATE_VARIABLES)) == ("CTA", "DATE", "LINK", "PRICE",
                                                "SOURCE", "TEXT", "TITLE"),
          str(TEMPLATE_VARIABLES))

    tpl = ("🔥 {TITLE}\n{TEXT}\n\n💰 Narxi: {PRICE}\n👉 {CTA}: {LINK}\n"
           "📅 {DATE} ({SOURCE})")
    check("barcha 7 o'zgaruvchi aniqlanadi",
          extract_variables(tpl) == ["CTA", "DATE", "LINK", "PRICE",
                                     "SOURCE", "TEXT", "TITLE"],
          str(extract_variables(tpl)))
    check("noma'lum {FOO} aniqlanmaydi",
          extract_variables("{FOO} {TITLE}") == ["TITLE"])

    values = {
        "title": "Yangi chegirma",          # kichik harf kaliti ham ishlaydi
        "TEXT": "Barcha mahsulotlar 30% chegirma!",
        "price": "99 000 so'm",
        "link": "t.me/shop",
        "cta": "Buyurtma bering",
        "source": "@dokon",
        # DATE kiritilmagan — avtomatik bugungi sana
    }
    r = render_template(tpl, values, date_value="21.09.2026")
    check("render ok", r["ok"] is True, str(r))
    expected = ("🔥 Yangi chegirma\nBarcha mahsulotlar 30% chegirma!\n\n"
                "💰 Narxi: 99 000 so'm\n👉 Buyurtma bering: t.me/shop\n"
                "📅 21.09.2026 (@dokon)")
    check("matn AYNAN kutilgandek almashtirildi", r["text"] == expected,
          repr(r["text"]))
    check("7 ta o'zgaruvchi almashtirildi", len(r["replaced"]) == 7,
          str(r["replaced"]))
    check("missing ro'yxati bo'sh", r["missing"] == [], str(r["missing"]))

    # Kiritilmagan (DATE'dan boshqa) o'zgaruvchi → bo'sh satr
    r2 = render_template("Sarlavha: {TITLE} — {PRICE}", {"title": "X"},
                         date_value="01.01.2026")
    check("kiritilmagan o'zgaruvchi bo'sh satrga aylandi",
          r2["text"] == "Sarlavha: X — ", repr(r2["text"]))
    check("missing: PRICE", r2["missing"] == ["PRICE"], str(r2["missing"]))

    # Noma'lum qavs TEGILMASDAN qoladi
    r3 = render_template("{TITLE} — {FOO}", {"title": "A"},
                         date_value="01.01.2026")
    check("noma'lum {FOO} saqlanib qoldi", r3["text"] == "A — {FOO}",
          repr(r3["text"]))

    # parse_variable_values: foydalanuvchi kiritishi
    parsed = parse_variable_values(
        "TITLE: Chegirma haftaligi\n price = 50%\nBOG'LANMAGAN QATOR\nFOO: x",
        expected=["TITLE", "PRICE", "TEXT"])
    check("NOMI: qiymat parsing (registrga bog'liq emas)",
          parsed == {"TITLE": "Chegirma haftaligi", "PRICE": "50%"},
          str(parsed))

    # validatsiya
    ok, _ = validate_template_content("Yaxshi shablon {TITLE}")
    check("yaroqli matn OK", ok is True)
    ok2, reason = validate_template_content("")
    check("bo'sh matn RAD", ok2 is False and reason == "empty")
    ok3, reason3 = validate_template_content("x" * 4001)
    check("4000+ belgi RAD", ok3 is False and reason3 == "too_long")

    # i18n paritet
    check("autopilot i18n pariteti (uz/ru/en)",
          all(autopilot_parity_report().values()), str(autopilot_parity_report()))
    check("templates i18n pariteti (uz/ru/en)",
          all(templates_parity_report().values()), str(templates_parity_report()))


# ---------------------------------------------------------------------------
# TEST 7 — 🗃 post_templates DB qatlami (real funksiyalar + fake cursor)
# ---------------------------------------------------------------------------
def test_templates_db_layer():
    print("\n== TEST 7: 🗃 post_templates — DB CRUD (real funksiyalar) ==")

    store = FakeStore()

    content = "🔥 {TITLE}\n{TEXT}\n\n💰 {PRICE}\n👉 {CTA}: {LINK}"
    tid = _with_db(store, lambda: _create_tpl(
        USER_ID, "Chegirma e'loni", content, CH_ID,
        ["CTA", "LINK", "PRICE", "TEXT", "TITLE"]))
    check("shablon yaratildi (id > 0)", tid and int(tid) > 0, str(tid))

    tid2 = _with_db(store, lambda: _create_tpl(
        USER_ID, "Ikkinchi shablon", "Oddiy matn", CH_ID, []))
    check("ikkinchi shablon yaratildi", tid2 and int(tid2) != int(tid))

    # ro'yxat: faqat o'ziniki
    lst = _with_db(store, lambda: _get_tpls(USER_ID))
    check("ro'yxat: 2 ta shablon", len(lst) == 2, str(len(lst)))
    first = next((t for t in lst if t["name"] == "Chegirma e'loni"), None)
    check("variables JSONB'dan list sifatida o'qildi",
          first is not None and isinstance(first["variables"], list)
          and "TITLE" in first["variables"], str(first and first["variables"]))
    check("content aynan saqlandi", first is not None
          and first["content"] == content)
    check("channel_id saqlandi", first is not None
          and first["channel_id"] == CH_ID)

    # bitta shablon: EGASI uchun
    got = _with_db(store, lambda: _get_tpl(int(tid), USER_ID))
    check("egasi shablonni ko'radi", got is not None and got["name"] ==
          "Chegirma e'loni", str(got and got["name"]))

    # --- IDOR: begona uchun ---
    foreign = _with_db(store, lambda: _get_tpl(int(tid), OTHER_USER_ID))
    check("IDOR: begona shablonni KO'RA OLmaydi (None)",
          foreign is None, str(foreign))

    # begonaning ro'yxati bo'sh
    other_list = _with_db(store, lambda: _get_tpls(OTHER_USER_ID))
    check("IDOR: begonaning ro'yxati bo'sh", other_list == [], str(other_list))

    # --- o'chirish: IDOR ---
    del_foreign = _with_db(store, lambda: _delete_tpl(int(tid), OTHER_USER_ID))
    check("IDOR: begona o'chira olmaydi (False)", del_foreign is False)
    check("IDOR: shablon joyida qoldi", int(tid) in store.templates)

    del_own = _with_db(store, lambda: _delete_tpl(int(tid), USER_ID))
    check("egasi o'chiradi (True)", del_own is True)
    check("shablon o'chdi", int(tid) not in store.templates)
    check("begona shabloni tegilmagan", int(tid2) in store.templates)


async def _create_tpl(user_id, name, content, channel_id, variables):
    return db_mod.create_post_template(user_id, name, content,
                                       channel_id=channel_id,
                                       variables=variables)


async def _get_tpls(user_id):
    return db_mod.get_post_templates(user_id)


async def _get_tpl(tid, user_id):
    return db_mod.get_post_template(tid, user_id)


async def _delete_tpl(tid, user_id):
    return db_mod.delete_post_template(tid, user_id)


# ---------------------------------------------------------------------------
# TEST 8 — 🎛 Shablon handler oqimi
# ---------------------------------------------------------------------------
def test_templates_handler_flow():
    print("\n== TEST 8: 🎛 Shablonlar handler — menyu, yaratish, ishlatish ==")

    # --- 8.1 kirish: IDOR ---
    store = FakeStore()
    store.owners[CH_ID] = USER_ID
    store.channels[CH_ID] = (CH_ID, CH_TITLE, "friendly")
    q_bad = _Query(f"{CB_CHANNEL_TEMPLATES}{CH_ID}", user_id=OTHER_USER_ID)
    state = _with_db(store, lambda: TP.channel_templates_entry(
        _upd_query(q_bad), _ctx("uz")))
    check("IDOR: begona kanal uchun shablonlar ochilmaydi",
          state == ConversationEnd(), str(state))

    # --- 8.2 kirish: menyu (SPEKS: 3 amal + Orqaga) ---
    q = _Query(f"{CB_CHANNEL_TEMPLATES}{CH_ID}")
    state2 = _with_db(store, lambda: TP.channel_templates_entry(
        _upd_query(q), _ctx("uz")))
    check("menyu: TPL_MENU holati", state2 == TP.TPL_MENU, str(state2))
    menu_cbs = _cbs(q.screen.get("reply_markup"))
    check("menyu: [➕ Yangi shablon][📋 Shablonni ishlatish][🗑 O'chirish][◀️ Orqaga]",
          menu_cbs == ["tpl_new", "tpl_use", "tpl_del", "tpl_back"],
          str(menu_cbs))
    check("menyu: SPEKS yorliqlari",
          _labels(q.screen.get("reply_markup")) == ["➕ Yangi shablon",
                                                    "📋 Shablonni ishlatish",
                                                    "🗑 O'chirish", "◀️ Orqaga"],
          str(_labels(q.screen.get("reply_markup"))))

    # --- 8.3 [➕ Yangi shablon]: nom → matn → saqlash ---
    ctx = _ctx("uz")
    ctx.user_data[TP.UD_CHANNEL] = CH_ID
    ctx.user_data[TP.UD_TITLE] = CH_TITLE
    q_new = _Query("tpl_new")
    state3 = _with_db(store, lambda: TP.templates_menu_callback(
        _upd_query(q_new), ctx))
    check("yangi: nom so'raladi", state3 == TP.TPL_NEW_NAME, str(state3))

    msg = _Msg(text="Chegirma shabloni")
    state4 = _with_db(store, lambda: TP.template_name_received(
        _upd_msg(msg), ctx))
    check("nom qabul qilindi → matn so'raladi",
          state4 == TP.TPL_NEW_CONTENT, str(state4))

    msg2 = _Msg(text="🔥 {TITLE}\n{TEXT}\n\n💰 {PRICE}\n👉 {CTA}: {LINK}")
    state5 = _with_db(store, lambda: TP.template_content_received(
        _upd_msg(msg2), ctx))
    check("matn qabul qilindi → menyuga qaytadi",
          state5 == TP.TPL_MENU, str(state5))
    check("saqlandi xabari chiqdi",
          any("saqlandi" in m["text"] for m in msg2.sent),
          str([m["text"][:40] for m in msg2.sent]))
    saved = [t for t in store.templates.values() if t["user_id"] == USER_ID]
    check("shablon DB'ga tushdi", len(saved) == 1, str(len(saved)))
    check("variables aniqlanib saqlandi",
          "TITLE" in str(saved[0]["variables"]), str(saved[0]["variables"]))

    # --- 8.4 [📋 Shablonni ishlatish]: tanlash → o'zgaruvchilar → preview ---
    tpl_id = saved[0]["id"]
    q_use = _Query("tpl_use")
    state6 = _with_db(store, lambda: TP.templates_menu_callback(
        _upd_query(q_use), ctx))
    check("ishlatish: ro'yxat ko'rinadi", state6 == TP.TPL_USE_PICK,
          str(state6))
    check("ro'yxatda shablon tugmasi bor",
          f"tpl_pick:{tpl_id}" in _cbs(q_use.screen.get("reply_markup")),
          str(_cbs(q_use.screen.get("reply_markup"))))

    q_pick = _Query(f"tpl_pick:{tpl_id}")
    state7 = _with_db(store, lambda: TP.template_pick_callback(
        _upd_query(q_pick), ctx))
    check("shablon tanlandi: o'zgaruvchilar so'raladi",
          state7 == TP.TPL_USE_VARS, str(state7))
    vars_text = q_pick.screen.get("text", "")
    check("o'zgaruvchilar ro'yxati ko'rsatilgan",
          all(v in vars_text for v in ("TITLE", "TEXT", "PRICE", "CTA", "LINK")),
          vars_text[:120])

    # o'zgaruvchi qiymatlari → render → TO'G'RIDAN-TO'G'RI manual preview
    msg3 = _Msg(text="TITLE: Katta chegirma\nTEXT: Barcha mahsulotlar 30% "
                     "chegirma!\nPRICE: 99 000 so'm\nCTA: Buyurtma bering"
                     "\nLINK: t.me/shop")
    state8 = _with_db(store, lambda: TP.template_vars_received(
        _upd_msg(msg3), ctx))
    from handlers.manual_post import MANUAL_PREVIEW, UD_CONTENT
    check("render: manual preview holatiga o'tdi",
          state8 == MANUAL_PREVIEW, str(state8))
    check("render: matn UD_CONTENT'ga yozildi",
          ctx.user_data.get(UD_CONTENT) == (
              "🔥 Katta chegirma\nBarcha mahsulotlar 30% chegirma!\n\n"
              "💰 99 000 so'm\n👉 Buyurtma bering: t.me/shop"),
          repr(ctx.user_data.get(UD_CONTENT)))
    check("render: universal panel (mnp_) biriktirildi",
          "mnp_now" in _cbs(msg3.sent[-1].get("reply_markup")),
          str(_cbs(msg3.sent[-1].get("reply_markup")) if msg3.sent else []))
    check("render: matn o'zgartirilmagan (placeholder yo'q)",
          "{TITLE}" not in msg3.sent[-1]["text"])

    # --- 8.5 [🗑 O'chirish] ---
    q_del = _Query("tpl_del")
    state9 = _with_db(store, lambda: TP.templates_menu_callback(
        _upd_query(q_del), ctx))
    check("o'chirish: ro'yxat ko'rinadi", state9 == TP.TPL_DEL_PICK, str(state9))
    q_rmv = _Query(f"tpl_rmv:{tpl_id}")
    state10 = _with_db(store, lambda: TP.template_remove_callback(
        _upd_query(q_rmv), ctx))
    check("o'chirildi → menyuga qaytdi", state10 == TP.TPL_MENU, str(state10))
    check("shablon bazadan o'chdi", tpl_id not in store.templates)


# ---------------------------------------------------------------------------
# TEST 9 — 🔁 Dublikat detektori (PURE — AI chaqiruvisiz)
# ---------------------------------------------------------------------------
def test_duplicate_detector_pure():
    print("\n== TEST 9: 🔁 Dublikat detektori — yengil (AI'siz) algoritm ==")

    recent = ("🔥 Yangi mahsulot sotuvga chiqdi! Bugun chegirma 30 foiz "
              "hoziroq buyurtma bering va do'stlaringizga ulashing hamda "
              "obuna bo'ling hamda kanalimizda qoling")

    # 85%+ o'xshash (2 ta so'z o'zgargan — containment ~0.9)
    similar = ("🔥 Yangi mahsulot sotuvga chiqdi! Bugun chegirma 30 foiz "
               "hoziroq buyurtma bering va do'stlaringizga ulashing hamda "
               "obuna bo'ling hamda kanalimizda qoling!")
    r = check_duplicate(similar, [recent])
    check("85%+ o'xshash matn: duplicate=True",
          r["duplicate"] is True, str(r))
    check("ball > 0.85", r["score"] > DUPLICATE_THRESHOLD, str(r["score"]))
    check("o'xshash post topildi (matched_text)",
          r["matched_text"] == recent, str(r["matched_text"])[:40])
    check("SPEKS ogohlantirish matni AYNAN",
          DUPLICATE_WARNING_MESSAGE == "⚠️ O'xshash post topildi. Bu post "
          "yaqindagi postingizga juda o'xshaydi.", DUPLICATE_WARNING_MESSAGE)
    check("chegara 0.85", DUPLICATE_THRESHOLD == 0.85)

    # Butunlay boshqa matn
    different = ("Kofeynamizda yangi matcha latte taqdim etildi! Hafta "
                 "oxirigacha har bir ikkinchi stakan bepul, kelib ko'ring "
                 "va do'stlaringizga ayting")
    r2 = check_duplicate(different, [recent])
    check("boshqa matn: ogohlantirish YO'Q",
          r2["duplicate"] is False and r2["score"] <= 0.85, str(r2))

    # Aynan bir xil matn → 1.0
    r3 = check_duplicate(recent, [recent])
    check("aynan o'sha matn: 1.0", r3["duplicate"] is True
          and r3["score"] == 1.0, str(r3))

    # Juda qisqa matn → checked=False (to'sib bo'lmaydi)
    r4 = check_duplicate("Buyurtma", [recent, "Buyurtma bering"])
    check("juda qisqa matn: checked=False", r4["checked"] is False, str(r4))

    # 2 tokenli subset — containment guard (soxta 100% yo'q)
    check("qisqa subset guard: containment 0",
          containment_ratio("buyurtma bering", recent) == 0.0,
          str(containment_ratio("buyurtma bering", recent)))

    # Jaccard aniqligi
    check("jaccard: bir xil → 1.0", jaccard_similarity("a b c", "a b c") == 1.0)
    check("jaccard: yarmi umumiy",
          jaccard_similarity("a b c d", "a b c e") == 0.6,
          str(jaccard_similarity("a b c d", "a b c e")))
    check("normalizatsiya: registr va tinish belgisi",
          normalize_text("Salom, Dunyo!") == normalize_text("salom dunyo"),
          normalize_text("Salom, Dunyo!"))
    check("URL olib tashlanadi",
          "t.me" not in normalize_text("post https://t.me/shop haqida"),
          normalize_text("post https://t.me/shop haqida"))
    check("tokenize: unikal tokenlar",
          tokenize("a a b") == {"a", "b"}, str(tokenize("a a b")))

    # Ro'yxatdagi ENG yaqin post topiladi
    r5 = check_duplicate(similar, [different, recent, "uchunchi post matni"])
    check("ro'yxatdan eng o'xshashi topildi",
          r5["duplicate"] is True and r5["match_index"] == 1, str(r5))

    # AI moduli import qilinmagan — pure funksiyalar tarmoqsiz (statik ishora)
    import services.channels.duplicate_detector as dd
    src = Path(dd.__file__).read_text(encoding="utf-8")
    check("detektor kodi AI servisini CHAQRIMAYDI",
          "ai_service" not in src and "run_ai_chain" not in src, "")


# ---------------------------------------------------------------------------
# TEST 10 — 🔁 Integratsiya: screen + oddiy post chiqarilishidan oldin
# ---------------------------------------------------------------------------
def test_duplicate_integration():
    print("\n== TEST 10: 🔁 Dublikat — screen_post_for_duplicates + manual gate ==")

    recent = ("🔥 Yangi mahsulot sotuvga chiqdi! Bugun chegirma 30 foiz "
              "hoziroq buyurtma bering va do'stlaringizga ulashing hamda "
              "obuna bo'ling hamda kanalimizda qoling")
    similar = recent[:-1] + "!"

    # --- screen: egasi uchun tekshiruv ishlaydi ---
    store = default_store()
    store.history[CH_ID] = [recent]
    r = _with_db(store, lambda: screen_post_for_duplicates(
        CH_ID, USER_ID, similar))
    check("screen: egasi uchun duplicate=True",
          r.get("ok") is True and r.get("duplicate") is True, str(r))
    check("screen: SPEKS xabari qaytadi",
          r.get("message") == DUPLICATE_WARNING_MESSAGE, str(r.get("message")))

    # --- screen: IDOR (begona) ---
    r2 = _with_db(store, lambda: screen_post_for_duplicates(
        CH_ID, OTHER_USER_ID, similar))
    check("screen: IDOR → FORBIDDEN",
          r2.get("ok") is False and r2.get("error_code") == "FORBIDDEN",
          str(r2))

    # --- screen: kanal tarixi o'qilmasa → fail-soft (post to'silmaydi) ---
    # IDOR tekshiruvi ishlaydi (egasi aniqlanadi), lekin tarix o'qishda DB
    # yiqiladi — detektor postni to'sib qo'ymaydi.
    class _BrokenHistoryDB:
        def get_channel_owner_id(self, channel_id):
            return USER_ID

        def get_channel_posts_history(self, channel_id, limit=5):
            raise Exception("db down")

        async def run_db(self, fn, *args, **kwargs):
            if getattr(fn, "__name__", "") == "get_channel_owner_id":
                return USER_ID
            raise Exception("db down")

    r3 = asyncio.run(screen_post_for_duplicates(
        CH_ID, USER_ID, similar, db_module=_BrokenHistoryDB()))
    check("screen: DB xatosi → fail-soft (duplicate=False)",
          r3.get("ok") is True and r3.get("checked") is False
          and r3.get("duplicate") is False, str(r3))

    # --- manual _publish gate: dublikat → yozish TO'XTAYDI ---
    dup_store = default_store()
    dup_store.history[CH_ID] = [recent]
    ctx = _ctx("uz")
    ctx.user_data[MP.UD_CONTENT] = similar
    ctx.user_data[MP.UD_POST_TYPE] = "text"
    ctx.user_data[MP.UD_MODE] = MP.MODE_NOW
    msg = _Msg()
    state = _with_db(dup_store, lambda: MP._publish(
        msg, ctx, USER_ID, CH_ID, CH_TITLE, "uz"))
    check("manual gate: dublikatda yozish to'xtadi (preview'da qoldi)",
          state == MP.MANUAL_PREVIEW, str(state))
    check("manual gate: add_post CHAQIRILMADI",
          not any(c[0] == "add_post" for c in dup_store.calls),
          str([c[0] for c in dup_store.calls]))
    warned = [m for m in msg.sent if "O'xshash post topildi" in m["text"]]
    check("manual gate: SPEKS ogohlantirishi chiqdi", bool(warned))
    gate_cbs = _cbs(warned[-1].get("reply_markup")) if warned else []
    check("manual gate: [🚀 Baribir chiqarish][✨ AI bilan yangilash][❌ Bekor qilish]",
          gate_cbs == ["mnp_dup_go", "mnp_dup_ai", "mnp_cancel"], str(gate_cbs))

    # --- [🚀 Baribir chiqarish]: force flag bilan yoziladi ---
    ctx.user_data[MP.UD_DUP_FORCE] = True
    ctx.user_data[MP.UD_DUP_CHANNEL_ID] = CH_ID
    ctx.user_data[MP.UD_DUP_CHANNEL_TITLE] = CH_TITLE
    msg2 = _Msg()

    # add_post'ni soxtalashtiramiz (fake run_db values orqali emas —
    # _publish db.add_post'ni run_db bilan chaqiradi, store esa INSERT'ni
    # emulyatsiya qiladi; natija id > 0 bo'lishi kerak).
    state2 = _with_db(dup_store, lambda: MP._publish(
        msg2, ctx, USER_ID, CH_ID, CH_TITLE, "uz"))
    scheduled = [p for p in dup_store.posts if p["user_id"] == USER_ID]
    check("force: post yozildi (add_post ishladi)",
          len(scheduled) == 1, str(len(scheduled)))
    check("force: END (yakuniy ekran)",
          state2 == ConversationEnd(), str(state2))

    # --- dublikat YO'Q bo'lsa: gate aralashmaydi ---
    clean_store = default_store()
    clean_store.history[CH_ID] = ["Butunlay boshqa post — matcha latte "
                                  "taqdimoti haqida yangilik!"]
    ctx2 = _ctx("uz")
    ctx2.user_data[MP.UD_CONTENT] = similar
    ctx2.user_data[MP.UD_POST_TYPE] = "text"
    ctx2.user_data[MP.UD_MODE] = MP.MODE_NOW
    msg3 = _Msg()
    state3 = _with_db(clean_store, lambda: MP._publish(
        msg3, ctx2, USER_ID, CH_ID, CH_TITLE, "uz"))
    scheduled3 = [p for p in clean_store.posts if p["user_id"] == USER_ID]
    check("dublikatsiz: darhol yoziladi (limit 1 marta)",
          len(scheduled3) == 1 and state3 == ConversationEnd(),
          f"posts={len(scheduled3)} state={state3}")
    check("dublikatsiz: ogohlantirish chiqmadi",
          not any("O'xshash post topildi" in m["text"] for m in msg3.sent))


# ---------------------------------------------------------------------------
# TEST 11 — 🔐 IDOR: handler darajasida
# ---------------------------------------------------------------------------
def test_idor_handler_level():
    print("\n== TEST 11: 🔐 IDOR — boshqa foydalanuvchi shabloni ==")

    store = FakeStore()
    # USER_ID'ning shabloni; OTHER_USER_ID uni ko'rishga urinadi.
    tid = store_add_template(store, USER_ID, "Eganing shabloni",
                             "Maxfiy matn {TITLE}", ["TITLE"])

    ctx = _ctx("uz")
    ctx.user_data[TP.UD_CHANNEL] = CH_ID
    ctx.user_data[TP.UD_TITLE] = CH_TITLE
    ctx.user_data[TP.UD_TEMPLATE] = {"id": int(tid), "name": "Eganing shabloni",
                                     "content": "Maxfiy matn {TITLE}"}

    # Begona tpl_pick bosadi (payload manipulyatsiya).
    q = _Query(f"tpl_pick:{tid}", user_id=OTHER_USER_ID)
    state = _with_db(store, lambda: TP.template_pick_callback(
        _upd_query(q), ctx))
    check("IDOR: begona shablonni ishlata olmaydi → 'topilmadi'",
          state == TP.TPL_MENU and "topilmadi" in q.screen.get("text", ""),
          q.screen.get("text", "")[:60])
    check("IDOR: maxfiy matn OCHILMADI",
          "Maxfiy matn" not in q.screen.get("text", ""),
          q.screen.get("text", "")[:60])

    # Begona tpl_rmv bosadi.
    q2 = _Query(f"tpl_rmv:{tid}", user_id=OTHER_USER_ID)
    state2 = _with_db(store, lambda: TP.template_remove_callback(
        _upd_query(q2), ctx))
    check("IDOR: begona o'chira olmaydi → 'topilmadi'",
          state2 == TP.TPL_MENU and "topilmadi" in q2.screen.get("text", ""),
          q2.screen.get("text", "")[:60])
    check("IDOR: shablon joyida (o'chirilmagan)",
          int(tid) in store.templates, str(store.templates.keys()))

    # Begonaning sessiyasida render ham mumkin emas (UD_TEMPLATE begona uchun
    # get_post_template NULL qaytargani uchun yuqorida tekshirildi).
    check("begona user_data tozalandi", not ctx.user_data.get(TP.UD_TEMPLATE),
          str(ctx.user_data.get(TP.UD_TEMPLATE)))


def store_add_template(store, user_id, name, content, variables):
    """Yordamchi: shablonni real create funksiyasi orqali qo'shadi."""
    async def _add():
        return db_mod.create_post_template(
            user_id, name, content, channel_id=CH_ID, variables=variables)
    return _with_db(store, _add)


# ---------------------------------------------------------------------------
# TEST 12 — 🧱 Sxema, UI panel, routing, FSM unikalligi
# ---------------------------------------------------------------------------
def test_schema_ui_routing():
    print("\n== TEST 12: 🧱 Sxema + UI panel + routing + FSM unikalligi ==")

    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    db_src = (ROOT / "database.py").read_text(encoding="utf-8")

    # --- post_templates jadvali ---
    check("schema.sql: post_templates jadvali",
          "CREATE TABLE IF NOT EXISTS post_templates (" in schema)
    for col in ("id SERIAL PRIMARY KEY", "user_id BIGINT NOT NULL",
                "channel_id VARCHAR(255)", "name VARCHAR(128) NOT NULL",
                "content TEXT NOT NULL", "variables JSONB",
                "created_at TIMESTAMPTZ DEFAULT NOW()"):
        check(f"schema.sql: post_templates.{col.split()[0]} ustuni",
              col in schema, col)
    check("schema.sql: idx_post_templates_user indeksi",
          "CREATE INDEX IF NOT EXISTS idx_post_templates_user" in schema)
    check("database.py: init_db'da post_templates yaratiladi",
          db_src.count("CREATE TABLE IF NOT EXISTS post_templates") == 1)
    check("database.py: EXPECTED_TABLES'da post_templates",
          "post_templates" in db_mod.EXPECTED_TABLES)
    check("database.py: EXPECTED_INDEXES'da idx_post_templates_user",
          "idx_post_templates_user" in db_mod.EXPECTED_INDEXES)

    # --- kanal paneli: yangi tugmalar ---
    for lang in LANGS:
        kb = render_channel_panel(CH_ID, lang)
        cbs = _cbs(kb)
        labels = _labels(kb)
        check(f"[{lang}] panel: [🚀 AI Avtopilot] tugmasi",
              f"{CB_CHANNEL_AUTOPILOT}{CH_ID}" in cbs, str(cbs))
        check(f"[{lang}] panel: [📋 Shablonlar] tugmasi",
              f"{CB_CHANNEL_TEMPLATES}{CH_ID}" in cbs, str(cbs))
        check(f"[{lang}] panel: eski tugmalar saqlangan (DNA/BestTime/Sozlamalar/Orqaga)",
              f"{CB_CHANNEL_DNA}{CH_ID}" in cbs
              and f"{CB_CHANNEL_BEST_TIME}{CH_ID}" in cbs
              and CB_CHANNEL_BACK in cbs, str(cbs))
        check(f"[{lang}] panel: yorliqlar tarjima qilingan",
              any("Avtopilot" in t or "Автопилот" in t or "Autopilot" in t
                  for t in labels)
              and any("Shablon" in t or "Шаблон" in t or "Template" in t
                      for t in labels), str(labels))

    # 64 bayt chegarasi (uzun kanal id)
    long_id = "-100" + "7" * 40
    kb_long = render_channel_panel(long_id, "ru")
    oversized = [c for c in _cbs(kb_long) if callback_byte_len(c) > CALLBACK_DATA_MAX_BYTES]
    check("uzun channel_id: callback'lar <= 64 bayt", not oversized,
          str(oversized))

    # kanal paneli tugma matnlari pariteti (channels_queue)
    for key in ("cq_ch_btn_autopilot", "cq_ch_btn_templates"):
        values = {c: channels_queue_t(key, c) for c in LANGS}
        check(f"{key}: uchala tilda tarjima (farq qiladi)",
              all(values.values()) and values["ru"] != values["uz"]
              and values["en"] != values["uz"], str(values))

    # --- routing: handlerlar ro'yxatdan o'tgan ---
    # Eslatma: ap_/tpl_/mnp_ suhbat-holat handlerlari main ConversationHandler
    # ICHIDA yashaydi — suhbat faol bo'lmaganda ularni GLOBAL "stale" tarmog'i
    # ushlaydi (xavfsizlik). Shu sababli tekshiruv conv.states orqali o'tadi.
    app = _build_app()
    from telegram.ext import CallbackQueryHandler as _CQH
    from telegram.ext import ConversationHandler as _ConvH

    conv = next((h for h in _all_handlers(app)
                 if isinstance(h, _ConvH) and AP.AUTOPILOT_TOPIC in h.states),
                None)
    check("routing: main ConversationHandler topildi", conv is not None)
    if conv is None:
        raise RuntimeError("main_conv (AUTOPILOT_TOPIC bilan) topilmadi")

    # 1) kirish nuqtalari — entry_points ichida (IDOR tekshiruvi bilan)
    for data, module, fname in (
        (f"{CB_CHANNEL_AUTOPILOT}{CH_ID}", AP, "channel_autopilot_entry"),
        (f"{CB_CHANNEL_TEMPLATES}{CH_ID}", TP, "channel_templates_entry"),
    ):
        fn = getattr(module, fname)
        ok = any(isinstance(h, _CQH) and h.callback is fn
                 and h.check_update(_cb_update(data))
                 for h in conv.entry_points)
        check(f"routing: {data.split(':')[0]} → {fname}", ok)

    # 2) suhbat holatlari — conv.states ichida aniq fn + pattern bilan
    for data, module, fname, state in (
        ("ap_confirm", AP, "autopilot_confirm_callback", AP.AUTOPILOT_VIEW),
        ("ap_force", AP, "autopilot_force_callback", AP.AUTOPILOT_VIEW),
        ("ap_refresh", AP, "autopilot_refresh_callback", AP.AUTOPILOT_VIEW),
        ("ap_regen", AP, "autopilot_regen_callback", AP.AUTOPILOT_VIEW),
        ("ap_edit", AP, "autopilot_edit_callback", AP.AUTOPILOT_VIEW),
        ("ap_cancel", AP, "autopilot_cancel_callback", AP.AUTOPILOT_VIEW),
        ("ap_eday:0", AP, "autopilot_edit_day_callback",
         AP.AUTOPILOT_EDIT_DAY),
        ("ap_cancel", AP, "autopilot_cancel_callback",
         AP.AUTOPILOT_EDIT_INPUT),
        ("tpl_new", TP, "templates_menu_callback", TP.TPL_MENU),
        ("tpl_back", TP, "templates_menu_callback", TP.TPL_USE_PICK),
        ("tpl_pick:1", TP, "template_pick_callback", TP.TPL_USE_PICK),
        ("tpl_rmv:1", TP, "template_remove_callback", TP.TPL_DEL_PICK),
        ("mnp_dup_go", MP, "manual_panel_callback", MP.MANUAL_PREVIEW),
        ("mnp_dup_ai", MP, "manual_panel_callback", MP.MANUAL_PREVIEW),
    ):
        fn = getattr(module, fname)
        ok = any(isinstance(h, _CQH) and h.callback is fn
                 and h.check_update(_cb_update(data))
                 for h in conv.states.get(state, []))
        check(f"routing: {data} @state={state} → {fname}", ok)

    # 3) stale tarmog'i — suhbat FAOL EMASligida stray callback xavfsiz yopiladi
    for data, fname in (("ap_confirm", "autopilot_stale_callback"),
                        ("tpl_pick:1", "templates_stale_callback")):
        h = _handler_for(app, _cb_update(data))
        cb = getattr(h, "callback", None)
        check(f"stale: {data} (suhbatsiz) → {fname}",
              cb is not None and getattr(cb, "__name__", "") == fname,
              str(cb))

    # --- FSM holatlari unikalligi ---
    all_states = {}
    for mod in (AP, TP, MP):
        for name in dir(mod):
            if name.isupper() and isinstance(getattr(mod, name), int):
                value = getattr(mod, name)
                if 400 <= value < 600:  # FSM holatlari oralig'i
                    all_states.setdefault(value, []).append(f"{mod.__name__}.{name}")
    dupes = {v: names for v, names in all_states.items() if len(names) > 1}
    check("FSM: 480–490 holatlari boshqa oqimlar bilan to'qnashmaydi",
          not dupes, str(dupes))
    check("FSM: avtopilot 480–483",
          (AP.AUTOPILOT_TOPIC, AP.AUTOPILOT_VIEW, AP.AUTOPILOT_EDIT_DAY,
           AP.AUTOPILOT_EDIT_INPUT) == (480, 481, 482, 483))
    check("FSM: shablonlar 485–490",
          (TP.TPL_MENU, TP.TPL_NEW_NAME, TP.TPL_NEW_CONTENT, TP.TPL_USE_PICK,
           TP.TPL_USE_VARS, TP.TPL_DEL_PICK) == (485, 486, 487, 488, 489, 490))

    # --- manual_post i18n hali ham paritetda (dublikat tugmalari qo'shildi) ---
    rep = manual_post_parity_report()
    check("manual_post i18n pariteti saqlangan (in_sync)",
          rep.get("in_sync") is True, str(rep))
    from keyboards.inline import CB_MANUAL_DUP_AI, CB_MANUAL_DUP_FORCE
    kb = get_duplicate_warning_keyboard("uz")
    check("dublikat klaviaturasi: 3 tugma (force/ai/cancel)",
          _cbs(kb) == [CB_MANUAL_DUP_FORCE, CB_MANUAL_DUP_AI, "mnp_cancel"],
          str(_cbs(kb)))
    check("manual panel kanonik tartibda (8 amal, 4 qator)",
          _cbs(get_manual_post_panel("uz")) == ["mnp_now", "mnp_time",
                                                "mnp_react", "mnp_url",
                                                "mnp_24h", "mnp_repeat",
                                                "mnp_edit", "mnp_cancel"],
          str(_cbs(get_manual_post_panel("uz"))))


def _build_app():
    from telegram.ext import ApplicationBuilder
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = ApplicationBuilder().token("123456:PHASE_C_TEST").build()
    H.register_all_handlers(app)
    return app


def _cb_update(data, user_id=USER_ID):
    from telegram import Update
    return Update.de_json({
        "update_id": 1,
        "callback_query": {
            "id": "cbq-1",
            "from": {"id": user_id, "is_bot": False, "first_name": "Tester"},
            "chat_instance": "pc-1",
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


def _all_handlers(app):
    return [h for group in sorted(app.handlers) for h in app.handlers[group]]


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    print("=" * 70)
    print(" 🧪 PHASE C — AI AUTOPILOT + POST SHABLONLARI + DUBLIKAT DETEKTOR")
    print("=" * 70)
    test_week_plan_formation()
    test_create_plan_service()
    test_quota_control()
    test_atomic_scheduling()
    test_autopilot_handler_flow()
    test_template_variables()
    test_templates_db_layer()
    test_templates_handler_flow()
    test_duplicate_detector_pure()
    test_duplicate_integration()
    test_idor_handler_level()
    test_schema_ui_routing()

    print("\n" + "=" * 70)
    print(f" JAMI: o'tdi={PASSED}, xato={FAILURES}")
    if FAILURES:
        print(" [FAIL] PHASE C TESTDA XATOLIKLAR BOR ^^^")
        return 1
    print(" PHASE C (AUTOPILOT + SHABLONLAR + DUBLIKAT) — 100% YASHIL ✔")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
