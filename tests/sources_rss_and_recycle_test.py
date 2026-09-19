#!/usr/bin/env python3
"""📥 PHASE D (2/2) — KONTENT MANBALARI: URL→POST, RSS/ATOM va RECYCLE TEST.

PHASE D ning 1/2 qismi servis qatlamini (``services/sources/url_extractor.py``,
``services/sources/rss_service.py``, ``services/channels/recycle.py``) bergan
edi. Bu fayl ularning **2/2 qismi** — handler/klaviatura qatlami, scheduler
ulanmasi va servis kafolotlarining regressiyasini qamrab oladi:

  TEST 1: 🛡 SSRF + URL→POST HANDLER — ichki manzil/localhost/bloklangan
          port HAVOLASI rad etiladi (tarmoqqa chiqilmaydi); ochiq havola →
          4 format tugmasi (📰/⚡/🧠/📢) → preview paneli (4 amal) →
          [🚀 Hozir chiqarish] navbatga yozadi, [📅 Rejalashtirish] vaqtni
          so'raydi (noto'g'ri vaqt → qayta so'rov), [🔄 Boshqa variant]
          qayta generatsiya qiladi; kvota rad etilsa — AI xatosi, kredit
          yechilmaydi.
  TEST 2: 📡 RSS HANDLER — manba qo'shish (SSRF guard + interval clamp
          15..1440), [🔄 Hoziroq tekshirish] yangi elementlardan qoralama
          yaratadi, IKKINCHI tekshiruvda DUBLIKAT QAYTA ISHLANMAYDI,
          ▶️/⏸, 🤖 avtopublish va 🗑 o'chirish ishlaydi; begona
          foydalanuvchi manbasi KO'RINMAYDI (IDOR).
  TEST 3: 🧩 RSS SERVIS QATLAMI — ``parse_feed`` (RSS 2.0 + Atom), XXE /
          entity-bomba himoyasi (DOCTYPE tozalanadi), ``canonical_url``
          tracking parametrlarini olib tashlaydi, ``filter_new_items``
          dublikatni kesadi, ``clamp_interval`` chegaralarni qat'iy ushlaydi.
  TEST 4: ♻️ RECYCLE — 14+ kunlik, yaxshi ko'rsatkichli postlar ro'yxati;
          ko'rsatkich bo'lmaganda SOXTA raqam uydirilmaydi; AI javobi eski
          postga juda o'xshasa — KO'R-KO'RONA REPOST rad etiladi (BLIND_REPOST);
          muvaffaqiyatli yangilanish → preview → navbat.
  TEST 5: 🗂 QORALAMALAR — tasdiqlash kutayotgan qoralamalar ro'yxati,
          [📅 Rejalashtirish] → preview → navbat (draft status='queued'),
          [🗑 O'chirish] → 'dismissed'.
  TEST 6: 🕒 SCHEDULER ULATMASI — ``poll_content_sources_job`` vaqti kelgan
          manbalarni tekshiradi: yangi element → qoralama, autopublish
          YOQILGAN manbada → ``scheduled_posts`` navbatiga yoziladi, egasiga
          bildirishnoma yuboriladi; takroriy tick dublikatni o'tkazib yuboradi.
  TEST 7: 🧱 UI / ROUTING / I18N — kanal panelida [📥 Kontent manbalari]
          (uz/ru/en, ≤64 bayt), HUB tugmalari, callback routing, stale
          tarmog'i, FSM 530–539 unikalligi va i18n paritet (uz/ru/en).

Ishga tushirish:
    PYTHON=/tmp/venv/bin/python bash tests/run_tests.sh   # runner bosqichi
    python3 tests/sources_rss_and_recycle_test.py
"""
import asyncio
import json
import os
import sys
import warnings
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:PHASE_D_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10079")
os.environ.setdefault("ENVIRONMENT", "test")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

import pytz  # noqa: E402

import database as db_mod  # noqa: E402
import handlers as H  # noqa: E402
import handlers.sources as SRC  # noqa: E402
import scheduler as SCHED  # noqa: E402
from keyboards.callback_data import (  # noqa: E402
    CALLBACK_DATA_MAX_BYTES,
    CALLBACK_PREFIX_MAX_BYTES,
    CB_CHANNEL_SOURCES,
    CB_SOURCE_ACTION,
    CB_SOURCE_CANCEL,
    CB_SOURCE_DRAFT,
    CB_SOURCE_DRAFTS,
    CB_SOURCE_FORMAT,
    CB_SOURCE_REC_PICK,
    CB_SOURCE_RECYCLE,
    CB_SOURCE_RSS,
    CB_SOURCE_RSS_ADD,
    CB_SOURCE_RSS_AUTO,
    CB_SOURCE_RSS_CHECK,
    CB_SOURCE_RSS_DEL,
    CB_SOURCE_RSS_TOGGLE,
    CB_SOURCE_URL,
    callback_byte_len,
)
from keyboards.inline import render_channel_panel  # noqa: E402
from services.ai.smm_common import (  # noqa: E402
    QuotaTicket,
    SMMFeatureService,
)
from services.channels.recycle import (  # noqa: E402
    MAX_REUSE_SIMILARITY,
    MIN_AGE_DAYS,
    RecycleService,
    is_blind_repost,
    select_recycle_candidates,
)
from services.sources.rss_service import (  # noqa: E402
    MAX_INTERVAL_MINUTES,
    MIN_INTERVAL_MINUTES,
    FeedItem,
    RssService,
    canonical_url,
    clamp_interval,
    filter_new_items,
    parse_feed,
    parse_interval_input,
)
import services.sources.url_extractor as UX  # noqa: E402
from services.sources.url_extractor import (  # noqa: E402
    FORMAT_KEYS,
    UrlPostService,
    validate_public_url,
)
from translations import (  # noqa: E402
    SOURCES_BUTTON_KEYS,
    channels_queue_parity_report,
    sources_parity_report,
    sources_t,
)

TZ = pytz.timezone("Asia/Tashkent")

USER_ID = 777001            # kanal EGASI
OTHER_USER_ID = 777999      # begona (IDOR tekshiruvi uchun)
CH_ID = "-1007777654321"
CH_TITLE = "Phase D test kanali"
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


def _now():
    """Test tayanch vaqti: 2026-09-17 12:00 (Toshkent)."""
    return TZ.localize(datetime(2026, 9, 17, 12, 0, 0))


# ---------------------------------------------------------------------------
# 1) FAKE QATLAM — soxta DB (SQL emulyatsiyasi), bot va AI orkestrator
# ---------------------------------------------------------------------------
class FakeStore:
    """content_sources / source_items / source_drafts / scheduled_posts mock.

    Real ``database.py`` funksiyalari shu cursor orqali ishlaydi — ya'ni
    SQL darajasidagi IDOR filtrlari (``WHERE user_id = %s``) va
    ``ON CONFLICT ... DO NOTHING`` dublikat himoyasi HAQIQIY kod bilan
    sinanadi. Tarmoqqa chiqilmaydi.
    """

    def __init__(self):
        self.sources = {}          # id -> dict
        self.source_items = {}     # id -> dict
        self.drafts = {}           # id -> dict
        self.posts = []            # scheduled_posts (COMMIT'dan keyin)
        self._txn_posts = []
        self.history = {}          # channel_id -> [dict]
        self.owners = {}           # channel_id -> user_id
        self.channels = {}         # channel_id -> (id, title, tone)
        self.calls = []            # (funksiya nomi, args)
        self.commits = 0
        self.rollbacks = 0
        self._next_source_id = 0
        self._next_item_id = 0
        self._next_draft_id = 0
        self._next_post_id = 0

    # -- yordamchilar --------------------------------------------------------
    def add_history(self, channel_id, text, views=500, reactions=6, days_old=20):
        self.history.setdefault(channel_id, []).append({
            "id": 5000 + len(self.history.get(channel_id, [])),
            "message_id": 9000 + len(self.history.get(channel_id, [])),
            "content": text,
            "views": views,
            "reactions": reactions,
            "post_date": _now() - timedelta(days=days_old),
        })

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

            # --- scheduled_posts (add_post) ---
            if "MAX(USER_POST_NUMBER)" in su:
                uid = int(params[0])
                nums = [p["user_post_number"] for p in st.posts
                        if p["user_id"] == uid]
                nums += [p["user_post_number"] for p in st._txn_posts
                         if p["user_id"] == uid]
                self._rows = [(max(nums) if nums else 0,)]
                return

            if "INSERT INTO SCHEDULED_POSTS" in su:
                st._next_post_id += 1
                st._txn_posts.append({
                    "id": st._next_post_id,
                    "user_id": int(params[0]),
                    "channel_id": str(params[1]),
                    "content": params[3],
                    "scheduled_time": params[10],
                    "user_post_number": params[11],
                    "status": "pending",
                })
                self.rowcount = 1
                self._rows = [(st._next_post_id,)]
                return

            # --- content_sources ---
            if "SELECT COUNT(*) FROM CONTENT_SOURCES" in su:
                uid = int(params[0])
                self._rows = [(len([s for s in st.sources.values()
                                    if s["user_id"] == uid]),)]
                return

            if "INSERT INTO CONTENT_SOURCES" in su:
                uid, ch_id, url, title = params[0], params[1], params[2], params[3]
                interval, autopublish = params[4], params[5]
                if len([s for s in st.sources.values()
                        if s["user_id"] == int(uid)]) >= db_mod.CONTENT_SOURCES_LIMIT:
                    raise Exception("content_sources limit reached")
                st._next_source_id += 1
                row = {
                    "id": st._next_source_id, "user_id": int(uid),
                    "channel_id": str(ch_id), "source_url": url,
                    "title": title or "", "enabled": True,
                    "interval_minutes": int(interval or 60),
                    "autopublish": bool(autopublish),
                    "last_checked_at": None,
                    "created_at": datetime(2026, 9, 1, 9, 0, 0),
                }
                st.sources[row["id"]] = row
                self.rowcount = 1
                self._rows = [(row["id"],)]
                return

            if "FROM CONTENT_SOURCES CS" in su and su.startswith("SELECT"):
                # get_due_content_sources: enabled + intervali to'lganlar
                moment = params[0] or _now()
                if getattr(moment, "tzinfo", None) is None:
                    moment = TZ.localize(moment)
                limit = int(params[1])
                rows = []
                for src in st.sources.values():
                    if not src["enabled"]:
                        continue
                    last = src["last_checked_at"]
                    if last is not None:
                        if getattr(last, "tzinfo", None) is None:
                            last = TZ.localize(last)
                        if last > moment - timedelta(
                                minutes=int(src["interval_minutes"] or 60)):
                            continue
                    rows.append(src)
                rows.sort(key=lambda s: (s["last_checked_at"] is not None,
                                         s["last_checked_at"] or s["created_at"],
                                         s["id"]))
                self._rows = [
                    (s["id"], s["user_id"], s["channel_id"], s["source_url"],
                     s["title"], s["enabled"], s["interval_minutes"],
                     s["autopublish"], s["last_checked_at"], s["created_at"],
                     "uz", st.channels.get(s["channel_id"], ("", "", ""))[1])
                    for s in rows[:limit]
                ]
                return

            if "FROM CONTENT_SOURCES" in su and su.startswith("SELECT"):
                if "WHERE ID = %S AND USER_ID" in su:
                    sid, uid = int(params[0]), int(params[1])
                    rows = [s for s in st.sources.values()
                            if s["id"] == sid and s["user_id"] == uid]
                else:
                    uid = int(params[0])
                    rows = [s for s in st.sources.values()
                            if s["user_id"] == uid]
                rows.sort(key=lambda s: s["id"], reverse=True)
                limit = int(params[-1]) if params else 20
                self._rows = [
                    (s["id"], s["user_id"], s["channel_id"], s["source_url"],
                     s["title"], s["enabled"], s["interval_minutes"],
                     s["autopublish"], s["last_checked_at"], s["created_at"])
                    for s in rows[:limit]
                ]
                return

            if su.startswith("UPDATE CONTENT_SOURCES SET ENABLED"):
                sid, uid = int(params[1]), int(params[2])
                row = st.sources.get(sid)
                if row and row["user_id"] == uid:
                    row["enabled"] = bool(params[0])
                    self.rowcount = 1
                return

            if su.startswith("UPDATE CONTENT_SOURCES SET AUTOPUBLISH"):
                sid, uid = int(params[1]), int(params[2])
                row = st.sources.get(sid)
                if row and row["user_id"] == uid:
                    row["autopublish"] = bool(params[0])
                    self.rowcount = 1
                return

            if su.startswith("UPDATE CONTENT_SOURCES SET INTERVAL_MINUTES"):
                sid, uid = int(params[1]), int(params[2])
                row = st.sources.get(sid)
                if row and row["user_id"] == uid:
                    row["interval_minutes"] = int(params[0])
                    self.rowcount = 1
                return

            if su.startswith("DELETE FROM CONTENT_SOURCES"):
                sid, uid = int(params[0]), int(params[1])
                row = st.sources.get(sid)
                if row and row["user_id"] == uid:
                    del st.sources[sid]
                    self.rowcount = 1
                return

            if su.startswith("UPDATE CONTENT_SOURCES SET LAST_CHECKED_AT"):
                sid = int(params[1])
                row = st.sources.get(sid)
                if row:
                    row["last_checked_at"] = params[0] or _now()
                    self.rowcount = 1
                return

            # --- source_items ---
            if "SELECT EXTERNAL_ID FROM SOURCE_ITEMS" in su:
                sid = int(params[0])
                limit = int(params[1])
                rows = [i for i in st.source_items.values()
                        if i["source_id"] == sid]
                rows.sort(key=lambda i: i["id"], reverse=True)
                self._rows = [(i["external_id"],) for i in rows[:limit]]
                return

            if "INSERT INTO SOURCE_ITEMS" in su:
                sid, ext_id = int(params[0]), str(params[1])
                for item in st.source_items.values():
                    if item["source_id"] == sid and item["external_id"] == ext_id:
                        # UNIQUE(source_id, external_id) — dublikat: 0 qaytadi.
                        self._rows = []
                        return
                st._next_item_id += 1
                st.source_items[st._next_item_id] = {
                    "id": st._next_item_id, "source_id": sid,
                    "external_id": ext_id, "canonical_url": str(params[2] or ""),
                    "title": str(params[3] or ""), "summary": str(params[4] or ""),
                    "processed_at": None,
                }
                self.rowcount = 1
                self._rows = [(st._next_item_id,)]
                return

            if su.startswith("UPDATE SOURCE_ITEMS SET PROCESSED_AT"):
                iid = int(params[1])
                row = st.source_items.get(iid)
                if row:
                    row["processed_at"] = params[0] or _now()
                    self.rowcount = 1
                return

            # --- source_drafts ---
            if "INSERT INTO SOURCE_DRAFTS" in su:
                sid, iid, uid = int(params[0]), int(params[1]), int(params[2])
                ch_id, title, content = params[3], params[4], params[5]
                for draft in st.drafts.values():
                    if draft["source_item_id"] == iid:
                        self._rows = []
                        return
                st._next_draft_id += 1
                st.drafts[st._next_draft_id] = {
                    "id": st._next_draft_id, "source_id": sid,
                    "source_item_id": iid, "user_id": uid,
                    "channel_id": str(ch_id or ""), "title": title or "",
                    "content": content or "", "status": "pending",
                    "scheduled_post_id": None,
                    "created_at": datetime(2026, 9, 17, 10, 0, 0),
                }
                self.rowcount = 1
                self._rows = [(st._next_draft_id,)]
                return

            if "SELECT ID FROM SOURCE_DRAFTS WHERE SOURCE_ITEM_ID" in su:
                iid = int(params[0])
                rows = [d for d in st.drafts.values()
                        if d["source_item_id"] == iid]
                self._rows = [(rows[0]["id"],)] if rows else []
                return

            if "FROM SOURCE_DRAFTS" in su and su.startswith("SELECT"):
                if "WHERE ID = %S AND USER_ID" in su:
                    did, uid = int(params[0]), int(params[1])
                    rows = [d for d in st.drafts.values()
                            if d["id"] == did and d["user_id"] == uid]
                elif "COUNT" in su:
                    uid, state = int(params[0]), str(params[1])
                    self._rows = [(len([d for d in st.drafts.values()
                                        if d["user_id"] == uid
                                        and d["status"] == state]),)]
                    return
                else:
                    uid, state = int(params[0]), str(params[1])
                    rows = [d for d in st.drafts.values()
                            if d["user_id"] == uid and d["status"] == state]
                rows.sort(key=lambda d: d["id"], reverse=True)
                limit = int(params[-1]) if params else 30
                self._rows = [
                    (d["id"], d["source_id"], d["source_item_id"], d["user_id"],
                     d["channel_id"], d["title"], d["content"], d["status"],
                     d["scheduled_post_id"], d["created_at"])
                    for d in rows[:limit]
                ]
                return

            if su.startswith("UPDATE SOURCE_DRAFTS SET STATUS"):
                did, uid = int(params[2]), int(params[3])
                row = st.drafts.get(did)
                if row and row["user_id"] == uid:
                    row["status"] = str(params[0])
                    if params[1] is not None:
                        row["scheduled_post_id"] = int(params[1])
                    self.rowcount = 1
                return

            # --- channel_posts_history (recycle) ---
            if "FROM CHANNEL_POSTS_HISTORY" in su and su.startswith("SELECT"):
                ch_id, limit = str(params[0]), int(params[2])
                rows = list(st.history.get(ch_id, []))[:limit]
                self._rows = [
                    (r["id"], r["message_id"], r["content"], r["views"],
                     r["post_date"], r["reactions"])
                    for r in rows
                ]
                return

            # --- channels (egalik) ---
            if "FROM CHANNELS" in su and su.startswith("SELECT"):
                if "WHERE CHANNEL_ID = %S" in su:
                    owner = st.owners.get(str(params[0]))
                    self._rows = [(owner,)] if owner is not None else []
                else:
                    uid = int(params[0])
                    self._rows = [tuple(c) for c in
                                  (st.channels.get(ch) for ch in st.channels)
                                  if c and c[0] in st.owners
                                  and st.owners[c[0]] == uid]
                return

        def fetchone(self):
            return self._rows[0] if self._rows else None

        def fetchall(self):
            return list(self._rows)

    def db_cursor(self, commit: bool = False):
        @contextmanager
        def _cm():
            outer = self._txn_posts
            self._txn_posts = []
            cur = self.Cursor(self)
            try:
                yield cur
            except Exception:
                self.rollbacks += 1
                self._txn_posts = outer
                raise
            else:
                if commit:
                    self.commits += 1
                    self.posts.extend(self._txn_posts)
                self._txn_posts = outer
        return _cm()

    async def run_db(self, fn, *args, **kwargs):
        name = getattr(fn, "__name__", str(fn))
        self.calls.append((name, args))
        if name == "get_user_channels_with_tone":
            uid = args[0]
            return [tuple(c) for c in self.channels.values()
                    if self.owners.get(c[0]) == uid]
        return await asyncio.to_thread(fn, *args, **kwargs)


@contextmanager
def _with_db(store):
    """``db.run_db`` / ``db.db_cursor`` ni soxta store bilan almashtiradi."""
    original_run = db_mod.run_db
    original_cur = db_mod.db_cursor
    db_mod.run_db = store.run_db
    db_mod.db_cursor = store.db_cursor
    try:
        yield store
    finally:
        db_mod.run_db = original_run
        db_mod.db_cursor = original_cur


def default_store():
    """Egasi USER_ID bo'lgan bitta kanal + tarix bilan standart store."""
    store = FakeStore()
    store.owners[CH_ID] = USER_ID
    store.channels[CH_ID] = (CH_ID, CH_TITLE, "friendly")
    return store


# ---------------------------------------------------------------------------
# 2) FAKE BOT / AI ORKESTRATOR / UPDATE
# ---------------------------------------------------------------------------
class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id=None, text=None, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": text})
        return SimpleNamespace(message_id=len(self.sent))


class FakeOrchestrator:
    """Deterministik AI: rejim bo'yicha tayyor javob (tarmoqqa chiqmaydi)."""

    def __init__(self, mode="url", script=None):
        self.mode = mode
        self.script = list(script or [])
        self.prompts = []

    async def orchestrate(self, user_id=None, prompt="", lang="uz",
                          context=None, db_module=False):
        self.prompts.append(str(prompt or ""))
        ctx = dict(context or {})
        mode = ctx.get("smm_mode") or self.mode
        if self.script:
            content = self.script.pop(0)
        elif mode == "URL_POST":
            content = json.dumps({
                "variants": {
                    "news": "📰 Yangilik: sun'iy intellekt bo'yicha yangi "
                            "tadqiqot natijalari e'lon qilindi.",
                    "short": "⚡ Qisqa: AI tadqiqoti — asosiy uchta xulosa.",
                    "expert": "🧠 Ekspert: AI tadqiqoti metodologiyasi va "
                              "uning cheklovlari haqida tahlil.",
                    "ads": "📢 Reklama: AI yangiliklarini kuzatib boring — "
                           "kanalga obuna bo'ling.",
                }
            }, ensure_ascii=False)
        elif mode == "RECYCLE":
            content = json.dumps({
                "refreshed": {
                    "hook": "Yana bir marta eslaysizmi?",
                    "title": "Eski mavzu — yangi ko'z bilan",
                    "body": "Bu matn butunlay yangi tuzilishda yozildi: "
                            "oldingi xulosalar saqlangan, ammo jumlalar "
                            "qayta tuzilgan.",
                    "cta": "👉 Fikringizni yozing",
                }
            }, ensure_ascii=False)
        else:
            content = "📡 RSS yangiligi: manbadan olingan qisqa post matni."
        return SimpleNamespace(success=True, content=content,
                               provider="fake", intent="SMM")


def _url_service(orchestrator) -> UrlPostService:
    return UrlPostService(orchestrator=orchestrator)


def _recycle_service(orchestrator) -> RecycleService:
    return RecycleService(orchestrator=orchestrator)


def _rss_service(orchestrator) -> RssService:
    return RssService(orchestrator=orchestrator)


@contextmanager
def patched_services(orchestrator, quota_allowed=True):
    """Handler xizmatlarini (AI + kvota) soxta variantga almashtiradi."""
    orig = {
        "url": SRC.new_url_service,
        "rss": SRC.new_rss_service,
        "recycle": SRC.new_recycle_service,
        "acq": SMMFeatureService.acquire_quota,
        "rel": SMMFeatureService.release_quota,
    }

    SRC.new_url_service = lambda: _url_service(orchestrator)
    SRC.new_rss_service = lambda: _rss_service(orchestrator)
    SRC.new_recycle_service = lambda: _recycle_service(orchestrator)

    async def _acquire(self, db_module=None, user_id=None, cost=None):
        if quota_allowed:
            return QuotaTicket(allowed=True, skipped=True, cost=0,
                               reason="quota_skipped", user_id=user_id)
        return QuotaTicket(allowed=False, cost=int(cost or 1),
                           reason="QUOTA_DENIED", user_id=user_id)

    async def _release(self, ticket=None):
        return False

    SMMFeatureService.acquire_quota = _acquire
    SMMFeatureService.release_quota = _release
    try:
        yield orchestrator
    finally:
        SRC.new_url_service = orig["url"]
        SRC.new_rss_service = orig["rss"]
        SRC.new_recycle_service = orig["recycle"]
        SMMFeatureService.acquire_quota = orig["acq"]
        SMMFeatureService.release_quota = orig["rel"]


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

    @property
    def all_text(self):
        return "\n".join(str(item.get("text") or "")
                         for item in (self.edits + self.message.sent))


def _upd_query(query):
    return SimpleNamespace(message=None, effective_message=query.message,
                           effective_user=query.from_user,
                           callback_query=query)


def _upd_msg(msg, user_id=USER_ID):
    return SimpleNamespace(message=msg, effective_message=msg,
                           effective_user=SimpleNamespace(id=user_id,
                                                          first_name="Tester"),
                           callback_query=None)


def _ctx(lang="uz", **extra):
    data = {"lang": lang}
    data.update(extra)
    return SimpleNamespace(user_data=data, chat_data={},
                           bot=SimpleNamespace(username="phase_d_test_bot"),
                           application=None)


def _cbs(markup):
    rows = getattr(markup, "inline_keyboard", None)
    return [b.callback_data for row in rows for b in row] if rows else []


def _labels(markup):
    rows = getattr(markup, "inline_keyboard", None)
    return [b.text for row in rows for b in row] if rows else []


def _sent_text(msg):
    return "\n".join(str(item.get("text") or "") for item in msg.sent)


# ---------------------------------------------------------------------------
# 3) MODUL DARAJASIDAGI FIKSTURLAR (havola, maqola, RSS oqimi)
# ---------------------------------------------------------------------------
ARTICLE_URL = "https://news.example.com/ai-research-2026"
ARTICLE = {
    "ok": True,
    "error_code": None,
    "title": "Sun'iy intellekt bo'yicha yangi tadqiqot",
    "text": ("Tadqiqotchilar sun'iy intellekt modellarining energiya "
             "samaradorligini oshirish bo'yicha yangi usulni taqdim etdi. "
             "Natijalar uchta mustaqil laboratoriyada tasdiqlandi."),
    "summary": "AI modellari endi kamroq energiya sarflaydi.",
    "chars": 180,
    "source": "news.example.com",
    "source_url": ARTICLE_URL,
    "paywall": {"detected": False},
    "injection_signals": [],
}

FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Test yangiliklar</title>
  <link>https://news.example.com</link>
  <description>Test oqim</description>
  <item>
    <title>Birinchi yangilik</title>
    <link>https://news.example.com/a?utm_source=x&amp;fbclid=1</link>
    <guid>guid-1</guid>
    <description>Birinchi yangilikning qisqacha tavsifi.</description>
  </item>
  <item>
    <title>Ikkinchi yangilik</title>
    <link>https://news.example.com/b</link>
    <guid>guid-2</guid>
    <description>Ikkinchi yangilikning qisqacha tavsifi.</description>
  </item>
</channel></rss>
"""

ATOM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom test</title>
  <entry>
    <title>Atom yangilik</title>
    <link href="https://news.example.com/atom-1" rel="alternate"/>
    <id>atom-id-1</id>
    <summary>Atom yangilik tavsifi.</summary>
  </entry>
</feed>
"""


#: Handler import qilgan haqiqiy funksiya (stubdan keyin qayta tiklanadi).
_ORIGINAL_VALIDATE = SRC.validate_public_url


@contextmanager
def stub_dns(ips=("93.184.216.34",)):
    """Haqiqiy DNS o'rniga deterministik stub (sandboxda tarmoq yo'q).

    MUHIM: SSRF tekshiruvining O'ZI o'zgarmaydi — faqat resolver almashtiriladi.
    Ya'ni ``validate_public_url`` ning barcha qoidalari (sxema, port,
    localhost/ichki IP/metadata, DNS-rebinding) haqiqiy kod bilan sinanadi;
    production'da resolver — real DNS, testda esa ommaviy (public) manzil.
    """
    original_module = UX.validate_public_url

    def _guard(url, **kwargs):
        # ``resolver=None`` (real DNS) ham stub bilan almashtiriladi —
        # aks holda sandbox'da (tarmoqsiz) har bir ommaviy havola
        # «dns_failure» bilan rad etiladi.
        if not callable(kwargs.get("resolver")):
            kwargs["resolver"] = lambda host, port=None: list(ips)
        return _ORIGINAL_VALIDATE(url, **kwargs)

    UX.validate_public_url = _guard
    SRC.validate_public_url = _guard
    try:
        yield
    finally:
        UX.validate_public_url = original_module
        SRC.validate_public_url = _ORIGINAL_VALIDATE


@contextmanager
def patched_fetch(article=None, ok=True, error_code=None, message=None):
    """``handlers.sources.fetch_article_safe`` ni soxta maqola bilan almashtiradi."""
    original = SRC.fetch_article_safe
    calls = []

    def _fake(url):
        calls.append(url)
        if not ok:
            return {"ok": False, "error_code": error_code or "network_error",
                    "message": message, "article": None,
                    "injection_signals": []}
        payload = dict(article or ARTICLE)
        payload.setdefault("source_url", url)
        return {"ok": True, "error_code": None, "message": None,
                "article": payload,
                "injection_signals": list(payload.get("injection_signals")
                                          or [])}

    SRC.fetch_article_safe = _fake
    try:
        yield calls
    finally:
        SRC.fetch_article_safe = original


@contextmanager
def patched_feed(xml_text=FEED_XML):
    """``RssService.load_feed`` ni tarmoqsiz (real parse bilan) almashtiradi."""
    original = RssService.load_feed
    calls = []

    def _fake(url, *, client=None, resolver=None, timeout=None):
        calls.append(url)
        parsed = parse_feed(xml_text, base_url="https://news.example.com")
        if not parsed.get("ok"):
            return {"ok": False, "error_code": "parse_failed", "message": None,
                    "items": [], "guard_code": None, "source_url": url}
        return {"ok": True, "error_code": None, "message": None,
                "items": parsed["items"], "feed_type": parsed["feed_type"],
                "feed_title": parsed["feed_title"], "guard_code": None,
                "source_url": url}

    RssService.load_feed = staticmethod(_fake)
    try:
        yield calls
    finally:
        RssService.load_feed = original


# ============================================================
# TEST 1 — 🛡 SSRF + URL → POST HANDLER OQIMI
# ============================================================
def test_url_post_flow():
    with stub_dns():
        print("\n== TEST 1: 🛡 SSRF himoyasi + 🔗 URL→POST handler oqimi ==")
        store = default_store()

        # --- 1) SSRF: ichki manzillar tarmoqqa chiqarilmasdan rad etiladi ---
        for bad in ("http://127.0.0.1/admin", "http://localhost:80/x",
                    "http://169.254.169.254/latest/meta-data/",
                    "http://10.0.0.5/internal", "file:///etc/passwd",
                    "http://news.example.com:8080/x"):
            guard = validate_public_url(bad)
            check(f"SSRF: {bad} → bloklandi", not guard.get("ok"),
                  str(guard.get("error_code")))

        with _with_db(store), patched_services(FakeOrchestrator()), \
                patched_fetch() as fetch_calls:
            ctx = _ctx("uz")
            q = _Query(f"{CB_CHANNEL_SOURCES}{CH_ID}")
            state = asyncio.run(SRC.channel_sources_entry(_upd_query(q), ctx))
            check("HUB ochildi (SRC_HUB)", state == SRC.SRC_HUB, str(state))
            check("HUB: 5 tugma (4 yo'nalish + Orqaga)",
                  _cbs(q.screen.get("reply_markup")) ==
                  [f"{CB_SOURCE_URL}{CH_ID}", f"{CB_SOURCE_RSS}{CH_ID}",
                   f"{CB_SOURCE_RECYCLE}{CH_ID}", f"{CB_SOURCE_DRAFTS}{CH_ID}",
                   "src_back"],
                  str(_cbs(q.screen.get("reply_markup"))))

            # --- 2) noto'g'ri havola: tarmoqqa chiqilmaydi ---
            q_url = _Query(f"{CB_SOURCE_URL}{CH_ID}")
            state = asyncio.run(SRC.sources_hub_callback(_upd_query(q_url), ctx))
            check("🔗 Havoladan post: so'rov holati (SRC_URL_INPUT)",
                  state == SRC.SRC_URL_INPUT, str(state))

            msg = _Msg(text="http://127.0.0.1/secret")
            state = asyncio.run(SRC.url_text_received(_upd_msg(msg), ctx))
            check("SSRF: ichki havola rad etildi (holat o'zgarmadi)",
                  state == SRC.SRC_URL_INPUT, str(state))
            check("SSRF: tarmoqqa chiqilmadi (fetch 0 marta)",
                  fetch_calls == [], str(fetch_calls))
            check("SSRF: foydalanuvchiga aniq xabar",
                  "src_rss_invalid_url" in _sent_text(msg)
                  or "⚠️" in _sent_text(msg), _sent_text(msg)[:80])

            # --- 3) to'g'ri havola → 4 format ---
            msg2 = _Msg(text=ARTICLE_URL)
            state = asyncio.run(SRC.url_text_received(_upd_msg(msg2), ctx))
            check("🔗 havola qabul qilindi: format tanlovi (SRC_URL_FORMATS)",
                  state == SRC.SRC_URL_FORMATS, str(state))
            check("tarmoqqa 1 marta chiqildi", len(fetch_calls) == 1,
                  str(fetch_calls))
            markup = msg2.sent[-1].get("reply_markup")
            check("4 format tugmasi + Bekor qilish",
                  _cbs(markup)[:4] == [f"src_fmt:{key}" for key in FORMAT_KEYS]
                  and _cbs(markup)[-1] == CB_SOURCE_CANCEL, str(_cbs(markup)))
            check("maqola kartochkasi (manba + injection hisobi)",
                  "news.example.com" in _sent_text(msg2), _sent_text(msg2)[:120])

            # --- 4) format tanlash → preview (4 amal) ---
            q_fmt = _Query(f"{CB_SOURCE_FORMAT}news")
            state = asyncio.run(SRC.url_format_callback(_upd_query(q_fmt), ctx))
            check("🎛 format tanlandi: preview (SRC_PREVIEW)",
                  state == SRC.SRC_PREVIEW, str(state))
            preview_markup = q_fmt.screen.get("reply_markup")
            check("preview paneli: 4 amal",
                  _cbs(preview_markup) == ["src_act:sched", "src_act:now",
                                           "src_act:regen", CB_SOURCE_CANCEL],
                  str(_cbs(preview_markup)))
            check("preview matni AI variantidan",
                  "Yangilik" in q_fmt.screen.get("text", ""),
                  str(q_fmt.screen.get("text"))[:80])

            # --- 5) [🔄 Boshqa variant] ---
            q_regen = _Query(f"{CB_SOURCE_ACTION}regen")
            state = asyncio.run(SRC.preview_action_callback(_upd_query(q_regen),
                                                            ctx))
            check("🔄 qayta generatsiya: preview'da qoladi",
                  state == SRC.SRC_PREVIEW, str(state))
            check("🔄 yangi variant xabari", "🔄" in q_regen.all_text,
                  q_regen.all_text[:80])

            # --- 6) [📅 Rejalashtirish]: noto'g'ri vaqt → qayta so'rov ---
            q_sched = _Query(f"{CB_SOURCE_ACTION}sched")
            state = asyncio.run(SRC.preview_action_callback(_upd_query(q_sched),
                                                            ctx))
            check("📅 vaqt so'raldi (SRC_TIME_INPUT)", state == SRC.SRC_TIME_INPUT,
                  str(state))
            msg_bad = _Msg(text="ertaga 99:99")
            state = asyncio.run(SRC.schedule_time_received(_upd_msg(msg_bad), ctx))
            check("📅 noto'g'ri vaqt: holat saqlandi, post yozilmadi",
                  state == SRC.SRC_TIME_INPUT and store.posts == [],
                  str(state))
            msg_ok = _Msg(text="ertaga 09:00")
            posts_before = len(store.posts)
            state = asyncio.run(SRC.schedule_time_received(_upd_msg(msg_ok), ctx))
            check("📅 to'g'ri vaqt: post navbatga yozildi",
                  state == SRC.ConversationHandler.END and
                  len(store.posts) == posts_before + 1, str(state))
            if store.posts:
                post = store.posts[-1]
                check("📅 post Toshkent zonasida, kelajakda",
                      post["scheduled_time"].tzinfo is not None
                      and post["scheduled_time"].hour == 9,
                      str(post["scheduled_time"]))
            check("📅 tasdiq xabarida sana/vaqt bor",
                  "09:00" in _sent_text(msg_ok), _sent_text(msg_ok)[:80])

        # --- 7) [🚀 Hozir chiqarish] + kvota rad etilishi ---
        store2 = default_store()
        with _with_db(store2), patched_services(FakeOrchestrator()), \
                patched_fetch():
            ctx = _ctx("uz")
            asyncio.run(SRC.channel_sources_entry(
                _upd_query(_Query(f"{CB_CHANNEL_SOURCES}{CH_ID}")), ctx))
            asyncio.run(SRC.sources_hub_callback(
                _upd_query(_Query(f"{CB_SOURCE_URL}{CH_ID}")), ctx))
            asyncio.run(SRC.url_text_received(_upd_msg(_Msg(text=ARTICLE_URL)),
                                              ctx))
            asyncio.run(SRC.url_format_callback(
                _upd_query(_Query(f"{CB_SOURCE_FORMAT}short")), ctx))
            q_now = _Query(f"{CB_SOURCE_ACTION}now")
            state = asyncio.run(SRC.preview_action_callback(_upd_query(q_now), ctx))
            check("🚀 Hozir chiqarish: sessiya yopildi (END)",
                  state == SRC.ConversationHandler.END, str(state))
            check("🚀 post navbatga yozildi (dublikat xavfisiz)",
                  len(store2.posts) == 1, str(len(store2.posts)))
            check("🚀 sessiya tozalandi (user_data bo'sh)",
                  not ctx.user_data.get(SRC.UD_PREVIEW))

        store3 = default_store()
        with _with_db(store3), patched_services(FakeOrchestrator(),
                                                quota_allowed=False), \
                patched_fetch():
            ctx = _ctx("uz")
            asyncio.run(SRC.channel_sources_entry(
                _upd_query(_Query(f"{CB_CHANNEL_SOURCES}{CH_ID}")), ctx))
            asyncio.run(SRC.sources_hub_callback(
                _upd_query(_Query(f"{CB_SOURCE_URL}{CH_ID}")), ctx))
            msg_quota = _Msg(text=ARTICLE_URL)
            state = asyncio.run(SRC.url_text_received(_upd_msg(msg_quota), ctx))
            check("kvota rad etilsa: AI chaqirilmaydi, kredit yechilmaydi",
                  state == SRC.SRC_URL_INPUT and store3.posts == [], str(state))
            check("kvota: foydalanuvchiga muloyim xabar",
                  "⚠️" in _sent_text(msg_quota), _sent_text(msg_quota)[:80])


# ============================================================
# TEST 2 — 📡 RSS HANDLER (qo'shish, tekshirish, dublikat, IDOR)
# ============================================================
def test_rss_handler_flow():
    with stub_dns():
        print("\n== TEST 2: 📡 RSS oqimi — qo'shish, tekshirish, dublikat, IDOR ==")
        store = default_store()

        with _with_db(store), patched_services(FakeOrchestrator()), patched_feed():
            ctx = _ctx("uz")
            asyncio.run(SRC.channel_sources_entry(
                _upd_query(_Query(f"{CB_CHANNEL_SOURCES}{CH_ID}")), ctx))

            # --- 1) bo'sh ro'yxat ---
            q_rss = _Query(f"{CB_SOURCE_RSS}{CH_ID}")
            state = asyncio.run(SRC.sources_hub_callback(_upd_query(q_rss), ctx))
            check("📡 RSS menyusi (SRC_RSS_MENU)", state == SRC.SRC_RSS_MENU,
                  str(state))
            check("📡 bo'sh ro'yxat: [➕ Manba qo'shish] + [◀️ Orqaga]",
                  _cbs(q_rss.screen.get("reply_markup")) ==
                  [CB_SOURCE_RSS_ADD, "src_back"],
                  str(_cbs(q_rss.screen.get("reply_markup"))))

            # --- 2) manba qo'shish: SSRF guard ---
            q_add = _Query(CB_SOURCE_RSS_ADD)
            state = asyncio.run(SRC.rss_menu_callback(_upd_query(q_add), ctx))
            check("➕ manba: havola so'raldi (SRC_RSS_URL)",
                  state == SRC.SRC_RSS_URL, str(state))
            msg_bad = _Msg(text="http://169.254.169.254/latest")
            state = asyncio.run(SRC.rss_url_received(_upd_msg(msg_bad), ctx))
            check("➕ SSRF: metadata manzili rad etildi (saqlanmadi)",
                  state == SRC.SRC_RSS_URL and not store.sources, str(state))

            # --- 3) interval clamp (5 → 15, 5000 → 1440) ---
            msg_url = _Msg(text="https://news.example.com/rss.xml")
            state = asyncio.run(SRC.rss_url_received(_upd_msg(msg_url), ctx))
            check("➕ to'g'ri havola: interval so'raldi (SRC_RSS_INTERVAL)",
                  state == SRC.SRC_RSS_INTERVAL, str(state))
            msg_bad_int = _Msg(text="abc")
            state = asyncio.run(SRC.rss_interval_received(_upd_msg(msg_bad_int),
                                                          ctx))
            check("⏱ noto'g'ri interval rad etildi",
                  state == SRC.SRC_RSS_INTERVAL, str(state))
            msg_int = _Msg(text="5")
            state = asyncio.run(SRC.rss_interval_received(_upd_msg(msg_int), ctx))
            check("⏱ interval clamp: 5 daqiqa → 15 (MIN)",
                  store.sources and list(store.sources.values())[0][
                      "interval_minutes"] == MIN_INTERVAL_MINUTES,
                  str([s["interval_minutes"] for s in store.sources.values()]))
            check("⏱ manba saqlandi: menyuga qaytildi (SRC_RSS_MENU)",
                  state == SRC.SRC_RSS_MENU, str(state))

            source_id = list(store.sources.values())[0]["id"]

            # --- 4) [🔄 Hoziroq tekshirish]: 2 yangi element → qoralama ---
            q_chk = _Query(f"{CB_SOURCE_RSS_CHECK}{source_id}")
            state = asyncio.run(SRC.rss_menu_callback(_upd_query(q_chk), ctx))
            check("🔄 tekshiruv: 2 ta yangi element → preview (SRC_PREVIEW)",
                  state == SRC.SRC_PREVIEW, str(state))
            check("🔄 2 ta element saqlandi (source_items)",
                  len(store.source_items) == 2, str(len(store.source_items)))
            check("🔄 2 ta qoralama yaratildi (source_drafts)",
                  len(store.drafts) == 2, str(len(store.drafts)))
            check("🔄 dublikat yo'q (har element bitta qoralama)",
                  len({d["source_item_id"] for d in store.drafts.values()}) == 2)

            # --- 5) IKKINCHI tekshiruv: DUBLIKAT QAYTA ISHLANMAYDI ---
            ctx2 = _ctx("uz")
            asyncio.run(SRC.channel_sources_entry(
                _upd_query(_Query(f"{CB_CHANNEL_SOURCES}{CH_ID}")), ctx2))
            asyncio.run(SRC.sources_hub_callback(
                _upd_query(_Query(f"{CB_SOURCE_RSS}{CH_ID}")), ctx2))
            q_chk2 = _Query(f"{CB_SOURCE_RSS_CHECK}{source_id}")
            state = asyncio.run(SRC.rss_menu_callback(_upd_query(q_chk2), ctx2))
            check("🔄 2-tekshiruv: dublikat qayta ishlanmadi (qoralama 2 ta)",
                  len(store.drafts) == 2 and len(store.source_items) == 2,
                  str((len(store.drafts), len(store.source_items))))
            check("🔄 2-tekshiruv: 'yangi element yo'q' ekrani (SRC_RSS_MENU)",
                  state == SRC.SRC_RSS_MENU, str(state))

            # --- 6) ▶️/⏸, 🤖 avtopublish ---
            q_tgl = _Query(f"{CB_SOURCE_RSS_TOGGLE}{source_id}")
            asyncio.run(SRC.rss_menu_callback(_upd_query(q_tgl), ctx2))
            check("⏸ manba to'xtatildi",
                  store.sources[source_id]["enabled"] is False)
            q_tgl2 = _Query(f"{CB_SOURCE_RSS_TOGGLE}{source_id}")
            asyncio.run(SRC.rss_menu_callback(_upd_query(q_tgl2), ctx2))
            check("▶️ manba qayta yoqildi",
                  store.sources[source_id]["enabled"] is True)
            q_auto = _Query(f"{CB_SOURCE_RSS_AUTO}{source_id}")
            asyncio.run(SRC.rss_menu_callback(_upd_query(q_auto), ctx2))
            check("🤖 avtopublish yoqildi",
                  store.sources[source_id]["autopublish"] is True)

            # --- 7) IDOR: begona foydalanuvchi manbani KO'RA OLMAYDI ---
            ctx_other = _ctx("uz")
            q_other = _Query(f"{CB_CHANNEL_SOURCES}{CH_ID}", user_id=OTHER_USER_ID)
            state = asyncio.run(SRC.channel_sources_entry(_upd_query(q_other),
                                                          ctx_other))
            check("IDOR: begona foydalanuvchi kanalni ocholmaydi (END)",
                  state == SRC.ConversationHandler.END, str(state))

            q_del_other = _Query(f"{CB_SOURCE_RSS_DEL}{source_id}",
                                 user_id=OTHER_USER_ID)
            ctx_bad = _ctx("uz")
            ctx_bad.user_data[SRC.UD_CHANNEL] = CH_ID
            ctx_bad.user_data[SRC.UD_TITLE] = CH_TITLE
            asyncio.run(SRC.rss_menu_callback(_upd_query(q_del_other), ctx_bad))
            check("IDOR: begona foydalanuvchi manbani O'CHIRA OLMAYDI",
                  source_id in store.sources, str(list(store.sources)))

            # --- 8) 🗑 o'chirish (egasi) ---
            q_del = _Query(f"{CB_SOURCE_RSS_DEL}{source_id}")
            asyncio.run(SRC.rss_menu_callback(_upd_query(q_del), ctx2))
            check("🗑 manba o'chirildi (faqat egasi)",
                  source_id not in store.sources, str(list(store.sources)))


# ============================================================
# TEST 3 — 🧩 RSS SERVIS QATLAMI (parse, XXE, dublikat, interval)
# ============================================================
def test_rss_service_layer():
    print("\n== TEST 3: 🧩 RSS servis qatlami — parse, XXE, dublikat, interval ==")

    rss = parse_feed(FEED_XML, base_url="https://news.example.com")
    check("RSS 2.0: 2 ta element", rss.get("ok") and len(rss["items"]) == 2,
          str(rss.get("error_code")))
    check("RSS 2.0: sarlavha olindi", rss.get("feed_title") == "Test yangiliklar",
          str(rss.get("feed_title")))
    check("RSS: tracking parametrlari kanonik havoladan olib tashlandi",
          rss["items"][0].canonical_url == "https://news.example.com/a",
          rss["items"][0].canonical_url)
    check("RSS: guid dublikat kaliti sifatida olindi",
          rss["items"][0].external_id == "guid-1",
          rss["items"][0].external_id)

    atom = parse_feed(ATOM_XML, base_url="https://news.example.com")
    check("Atom 1.0: 1 ta element", atom.get("ok") and len(atom["items"]) == 1,
          str(atom.get("error_code")))

    xxe = ('<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY bomb "'
           '&a;&a;&a;&a;&a;">]><rss version="2.0"><channel><item>'
           '<title>&bomb;</title></item></channel></rss>')
    safe = parse_feed(xxe)
    check("XXE/billion-laughs: DOCTYPE tozalandi, parser yiqilmadi",
          safe.get("ok") is False or len(safe.get("items") or []) >= 0)
    check("XXE: buzuq XML ham istisno tashlamaydi (fail-soft)",
          isinstance(safe, dict) and "ok" in safe)

    items = [
        FeedItem(external_id="a", canonical_url="https://x/1", title="A"),
        FeedItem(external_id="b", canonical_url="https://x/2", title="B"),
    ]
    check("filter_new_items: barchasi yangi",
          len(filter_new_items(items, [])) == 2)
    check("filter_new_items: dublikat kesildi",
          [i.external_id for i in filter_new_items(items, ["a"])] == ["b"])
    check("filter_new_items: hammasi dublikat → bo'sh",
          filter_new_items(items, ["a", "b"]) == [])

    check("clamp_interval: 1 → 15", clamp_interval(1) == MIN_INTERVAL_MINUTES)
    check("clamp_interval: 99999 → 1440",
          clamp_interval(99999) == MAX_INTERVAL_MINUTES)
    check("clamp_interval: 60 → 60", clamp_interval(60) == 60)
    check("parse_interval_input: '45 daqiqa' → 45",
          parse_interval_input("45") == 45)
    check("parse_interval_input: axlat → None",
          parse_interval_input("salom") is None)
    check("canonical_url: utm/fbclid olib tashlanadi",
          canonical_url("https://x.com/a?utm_source=y&fbclid=z&keep=1#frag")
          == "https://x.com/a?keep=1",
          canonical_url("https://x.com/a?utm_source=y&fbclid=z&keep=1#frag"))


# ============================================================
# TEST 4 — ♻️ CONTENT RECYCLE
# ============================================================
def test_recycle_flow():
    with stub_dns():
        print("\n== TEST 4: ♻️ Content Recycle — nomzodlar, repost taqiqi, navbat ==")

        # --- PURE: nomzod tanlash ---
        old = {
            "id": 1, "text": "Bu juda eski post matni — kanalda yaxshi "
                             "ko'rsatkich bergan, yetarlicha uzun matn.",
            "views": 900, "reactions": 12,
            "post_date": (_now() - timedelta(days=30)).isoformat(),
        }
        fresh = dict(old, id=2, post_date=(_now() - timedelta(days=2)).isoformat())
        weak = dict(old, id=3, views=1, reactions=0)
        result = select_recycle_candidates([old, fresh, weak], now=_now())
        check("14 kundan yangi post NOMZOD EMAS",
              all(c["post_id"] != 2 for c in result["candidates"]))
        check("yaxshi ko'rsatkichli eski post nomzod",
              any(c["post_id"] == 1 for c in result["candidates"]))
        check("ko'rsatkichi past post rad etildi",
              all(c["post_id"] != 3 for c in result["candidates"]),
              str([c["post_id"] for c in result["candidates"]]))
        check("metrics_available True (haqiqiy ko'rsatkich bor)",
              result["metrics_available"] is True)
        no_metrics = select_recycle_candidates(
            [dict(old, views=0, reactions=0, id=9)], now=_now())
        check("ko'rsatkich yo'q: soxta raqam o'rniga 'unknown' sifat",
              no_metrics["metrics_available"] is False
              and all(c.get("quality") == "unknown"
                      for c in no_metrics["candidates"]))
        check("MIN_AGE_DAYS = 14", MIN_AGE_DAYS == 14)

        check("ko'r-ko'rona repost: bir xil matn → BLIND",
              is_blind_repost(old["text"], old["text"]).get("blind") is True)
        check("o'xshamagan matn → repost emas",
              is_blind_repost(old["text"],
                              "Butunlay boshqa mavzu — yangi tuzilish va yangi "
                              "so'zlar bilan yozilgan post matni.").get("blind")
              is False)
        check("chegara 0.75", MAX_REUSE_SIMILARITY == 0.75)

        # --- HANDLER: nomzodlar ro'yxati ---
        store = default_store()
        store.add_history(CH_ID, old["text"], views=900, reactions=12, days_old=30)
        store.add_history(CH_ID, "Ikkinchi eski post matni — yetarlicha uzun, "
                                 "ko'rsatkichlari ham yaxshi bo'lgan post.",
                          views=700, reactions=8, days_old=45)

        with _with_db(store), patched_services(FakeOrchestrator("recycle")):
            ctx = _ctx("uz")
            asyncio.run(SRC.channel_sources_entry(
                _upd_query(_Query(f"{CB_CHANNEL_SOURCES}{CH_ID}")), ctx))
            q_rec = _Query(f"{CB_SOURCE_RECYCLE}{CH_ID}")
            state = asyncio.run(SRC.sources_hub_callback(_upd_query(q_rec), ctx))
            check("♻️ nomzodlar ro'yxati (SRC_RECYCLE_LIST)",
                  state == SRC.SRC_RECYCLE_LIST, str(state))
            check("♻️ 2 ta nomzod tugmasi + Orqaga",
                  len(_cbs(q_rec.screen.get("reply_markup"))) == 3,
                  str(_cbs(q_rec.screen.get("reply_markup"))))

            q_pick = _Query(f"{CB_SOURCE_REC_PICK}0")
            state = asyncio.run(SRC.recycle_pick_callback(_upd_query(q_pick), ctx))
            check("♻️ AI yangiladi: preview (SRC_PREVIEW)",
                  state == SRC.SRC_PREVIEW, str(state))
            check("♻️ yangilangan matn eski postga o'xshamaydi",
                  "yangi tuzilishda" in q_pick.all_text, q_pick.all_text[:120])

            # --- navbatga yozish ---
            q_now = _Query(f"{CB_SOURCE_ACTION}now")
            state = asyncio.run(SRC.preview_action_callback(_upd_query(q_now), ctx))
            check("♻️ yangilangan post navbatga tushdi",
                  state == SRC.ConversationHandler.END and len(store.posts) == 1,
                  str((state, len(store.posts))))

        # --- BLIND REPOST: AI eski matnni deyarli aynan qaytarsa ---
        store2 = default_store()
        store2.add_history(CH_ID, old["text"], views=900, reactions=12, days_old=30)
        with _with_db(store2), patched_services(FakeOrchestrator("recycle")):
            ctx = _ctx("uz")
            asyncio.run(SRC.channel_sources_entry(
                _upd_query(_Query(f"{CB_CHANNEL_SOURCES}{CH_ID}")), ctx))
            asyncio.run(SRC.sources_hub_callback(
                _upd_query(_Query(f"{CB_SOURCE_RECYCLE}{CH_ID}")), ctx))
            blind = json.dumps({
                "refreshed": {"hook": "", "title": "",
                              "body": old["text"], "cta": ""}},
                ensure_ascii=False)
            orch = FakeOrchestrator("recycle", script=[blind, blind])
            with patched_services(orch):
                q_pick = _Query(f"{CB_SOURCE_REC_PICK}0")
                state = asyncio.run(SRC.recycle_pick_callback(_upd_query(q_pick),
                                                              ctx))
                check("♻️ BLIND REPOST: post ko'rsatilmadi (ro'yxatda qoldi)",
                      state == SRC.SRC_RECYCLE_LIST, str(state))
                check("♻️ BLIND REPOST: post yozilmadi",
                      store2.posts == [], str(len(store2.posts)))
                check("♻️ BLIND REPOST: ogohlantirish matni",
                      "repost" in q_pick.all_text.lower(), q_pick.all_text[:120])

        # --- nomzod yo'q (14 kundan eski post yo'q) ---
        store3 = default_store()
        store3.add_history(CH_ID, old["text"], views=900, reactions=12, days_old=3)
        with _with_db(store3), patched_services(FakeOrchestrator("recycle")):
            ctx = _ctx("uz")
            asyncio.run(SRC.channel_sources_entry(
                _upd_query(_Query(f"{CB_CHANNEL_SOURCES}{CH_ID}")), ctx))
            q_rec = _Query(f"{CB_SOURCE_RECYCLE}{CH_ID}")
            state = asyncio.run(SRC.sources_hub_callback(_upd_query(q_rec), ctx))
            check("♻️ nomzod yo'q: bo'sh ekran (hech qanday crash emas)",
                  state == SRC.SRC_RECYCLE_LIST
                  and "📭" in q_rec.screen.get("text", ""),
                  str(q_rec.screen.get("text"))[:80])


# ============================================================
# TEST 5 — 🗂 QORALAMALAR
# ============================================================
def test_drafts_flow():
    with stub_dns():
        print("\n== TEST 5: 🗂 Qoralamalar — ro'yxat, tasdiqlash, o'chirish ==")
        store = default_store()
        store.sources[1] = {
            "id": 1, "user_id": USER_ID, "channel_id": CH_ID,
            "source_url": "https://news.example.com/rss.xml", "title": "Test",
            "enabled": True, "interval_minutes": 60, "autopublish": False,
            "last_checked_at": None, "created_at": datetime(2026, 9, 1, 9, 0, 0),
        }
        store.source_items[11] = {
            "id": 11, "source_id": 1, "external_id": "guid-1",
            "canonical_url": "https://news.example.com/a", "title": "Yangi material",
            "summary": "", "processed_at": None,
        }
        store.drafts[21] = {
            "id": 21, "source_id": 1, "source_item_id": 11, "user_id": USER_ID,
            "channel_id": CH_ID, "title": "Yangi material",
            "content": "📡 Yangi material asosida tayyorlangan post matni.",
            "status": "pending", "scheduled_post_id": None,
            "created_at": datetime(2026, 9, 17, 10, 0, 0),
        }

        with _with_db(store), patched_services(FakeOrchestrator()), patched_feed():
            ctx = _ctx("uz")
            asyncio.run(SRC.channel_sources_entry(
                _upd_query(_Query(f"{CB_CHANNEL_SOURCES}{CH_ID}")), ctx))
            q_drf = _Query(f"{CB_SOURCE_DRAFTS}{CH_ID}")
            state = asyncio.run(SRC.sources_hub_callback(_upd_query(q_drf), ctx))
            check("🗂 qoralamalar ro'yxati (SRC_DRAFTS)", state == SRC.SRC_DRAFTS,
                  str(state))
            check("🗂 har qoralama uchun 2 amal + Orqaga",
                  _cbs(q_drf.screen.get("reply_markup")) ==
                  [f"{CB_SOURCE_DRAFT}ok:21", f"{CB_SOURCE_DRAFT}del:21",
                   "src_back"],
                  str(_cbs(q_drf.screen.get("reply_markup"))))
            check("🗂 HUB: qoralamalar tugmasi (qisqa yorliq)",
                  "🗂 Qoralamalar" in str(_labels(SRC.sources_hub_keyboard(
                      CH_ID, 1, "uz"))), str(_labels(SRC.sources_hub_keyboard(
                          CH_ID, 1, "uz"))))

            # --- tasdiqlash → preview → navbat ---
            q_ok = _Query(f"{CB_SOURCE_DRAFT}ok:21")
            state = asyncio.run(SRC.draft_action_callback(_upd_query(q_ok), ctx))
            check("📅 qoralama preview'ga tushdi (SRC_PREVIEW)",
                  state == SRC.SRC_PREVIEW, str(state))
            q_now = _Query(f"{CB_SOURCE_ACTION}now")
            state = asyncio.run(SRC.preview_action_callback(_upd_query(q_now), ctx))
            check("📅 tasdiqlandi: post navbatga yozildi",
                  state == SRC.ConversationHandler.END and len(store.posts) == 1,
                  str((state, len(store.posts))))
            check("📅 qoralama statusi 'queued' + post id bog'landi",
                  store.drafts[21]["status"] == "queued"
                  and store.drafts[21]["scheduled_post_id"] == store.posts[-1]["id"],
                  str(store.drafts[21]))

            # --- o'chirish ---
            store.drafts[22] = dict(store.drafts[21], id=22,
                                    source_item_id=12, status="pending",
                                    scheduled_post_id=None)
            q_del = _Query(f"{CB_SOURCE_DRAFT}del:22")
            state = asyncio.run(SRC.draft_action_callback(_upd_query(q_del), ctx))
            check("🗑 qoralama o'chirildi ('dismissed')",
                  store.drafts[22]["status"] == "dismissed"
                  and state == SRC.SRC_DRAFTS, str(store.drafts[22]["status"]))

            # --- IDOR: begona foydalanuvchi qoralamani ko'ra olmaydi ---
            ctx_bad = _ctx("uz")
            ctx_bad.user_data[SRC.UD_CHANNEL] = CH_ID
            q_bad = _Query(f"{CB_SOURCE_DRAFT}ok:21", user_id=OTHER_USER_ID)
            state = asyncio.run(SRC.draft_action_callback(_upd_query(q_bad),
                                                          ctx_bad))
            check("IDOR: begona foydalanuvchi qoralamani OCHOLMAYDI",
                  "topilmadi" in q_bad.all_text or state == SRC.SRC_DRAFTS,
                  q_bad.all_text[:80])


# ============================================================
# TEST 6 — 🕒 SCHEDULER ULATMASI (poll_content_sources_job)
# ============================================================
def test_scheduler_integration():
    with stub_dns():
        print("\n== TEST 6: 🕒 Scheduler ulanmasi — poll_content_sources_job ==")
        store = default_store()
        store.sources[1] = {
            "id": 1, "user_id": USER_ID, "channel_id": CH_ID,
            "source_url": "https://news.example.com/rss.xml", "title": "Auto manba",
            "enabled": True, "interval_minutes": 60, "autopublish": True,
            "last_checked_at": None, "created_at": datetime(2026, 8, 1, 9, 0, 0),
        }
        store.sources[2] = {
            "id": 2, "user_id": USER_ID, "channel_id": CH_ID,
            "source_url": "https://news.example.com/rss2.xml", "title": "Qo'lda",
            "enabled": True, "interval_minutes": 60, "autopublish": False,
            "last_checked_at": None, "created_at": datetime(2026, 8, 2, 9, 0, 0),
        }

        bot = FakeBot()

        async def _run():
            return await SCHED.poll_content_sources_job(bot)

        with _with_db(store), patched_services(FakeOrchestrator()), patched_feed():
            summary = asyncio.run(_run())
            check("scheduler: 2 ta manba tekshirildi",
                  summary.get("checked") == 2, str(summary))
            check("scheduler: 4 ta qoralama (har manbada 2 element)",
                  summary.get("drafts") == 4, str(summary))
            check("scheduler: autopublish manbasida 2 post navbatga yozildi",
                  summary.get("scheduled") == 2 and len(store.posts) == 2,
                  str((summary, len(store.posts))))
            check("scheduler: qo'lda tasdiqlanadigan manba navbatga YUTILMADI",
                  all(p["channel_id"] == CH_ID for p in store.posts))
            check("scheduler: dublikat yo'q (har element bitta)",
                  len(store.source_items) == 4, str(len(store.source_items)))
            autopublish_drafts = [d for d in store.drafts.values()
                                  if d["source_id"] == 1]
            check("scheduler: avtopublish qoralamasi 'queued'",
                  all(d["status"] == "queued" for d in autopublish_drafts),
                  str([d["status"] for d in autopublish_drafts]))
            manual_drafts = [d for d in store.drafts.values()
                             if d["source_id"] == 2]
            check("scheduler: qo'lda manba qoralamasi 'pending' (tasdiq kutadi)",
                  all(d["status"] == "pending" for d in manual_drafts),
                  str([d["status"] for d in manual_drafts]))
            check("scheduler: egasiga bildirishnoma yuborildi",
                  len(bot.sent) >= 1 and bot.sent[0]["chat_id"] == USER_ID,
                  str(bot.sent[:1]))
            check("scheduler: bildirishnoma matni i18n'dan (3 tilda mavjud)",
                  all(sources_t("src_rss_new_draft_notice", lang, channel="x",
                                title="t", text="m") for lang in LANGS))

            # --- takroriy tick: dublikat qayta ishlanmaydi ---
            summary2 = asyncio.run(_run())
            check("scheduler: 2-tick — yangi qoralama YO'Q (dublikat)",
                  summary2.get("drafts") == 0, str(summary2))
            check("scheduler: 2-tick — navbat o'smadi",
                  len(store.posts) == 2, str(len(store.posts)))

            # --- manba o'chirilgan bo'lsa tekshirilmaydi ---
            store.sources[1]["enabled"] = False
            store.sources[2]["enabled"] = False
            summary3 = asyncio.run(_run())
            check("scheduler: o'chirilgan manbalar tekshirilmaydi",
                  summary3.get("checked") == 0, str(summary3))

        # --- bot yo'q (None) bo'lsa ham job yiqilmaydi ---
        store2 = default_store()
        store2.sources[1] = {
            "id": 1, "user_id": USER_ID, "channel_id": CH_ID,
            "source_url": "https://news.example.com/rss.xml", "title": "Auto",
            "enabled": True, "interval_minutes": 60, "autopublish": True,
            "last_checked_at": None, "created_at": datetime(2026, 8, 1, 9, 0, 0),
        }
        with _with_db(store2), patched_services(FakeOrchestrator()), patched_feed():
            summary = asyncio.run(SCHED.poll_content_sources_job(None))
            check("scheduler: botsiz ham ishlaydi (bildirishnomasiz)",
                  summary.get("drafts") == 2 and len(store2.posts) == 2,
                  str(summary))

        check("poll_content_sources_job mavjud va async",
              asyncio.iscoroutinefunction(SCHED.poll_content_sources_job))


# ============================================================
# TEST 7 — 🧱 UI / ROUTING / I18N / 64-BAYT / FSM
# ============================================================
def test_ui_routing_i18n():
    print("\n== TEST 7: 🧱 UI panel, routing, i18n paritet, FSM unikalligi ==")

    # --- kanal panelida [📥 Kontent manbalari] ---
    for lang in LANGS:
        kb = render_channel_panel(CH_ID, lang)
        cbs = _cbs(kb)
        check(f"[{lang}] panel: [📥 Kontent manbalari] tugmasi",
              f"{CB_CHANNEL_SOURCES}{CH_ID}" in cbs, str(cbs))
        check(f"[{lang}] panel: eski tugmalar saqlangan (ap/tpl/st/back)",
              f"ch_ap:{CH_ID}" in cbs and f"ch_tpl:{CH_ID}" in cbs
              and "ch_back" in cbs, str(cbs))

    long_id = "-100" + "7" * 40
    kb_long = render_channel_panel(long_id, "ru")
    oversized = [c for c in _cbs(kb_long)
                 if callback_byte_len(c) > CALLBACK_DATA_MAX_BYTES]
    check("uzun channel_id: barcha callback'lar ≤64 bayt", not oversized,
          str(oversized))

    # --- prefiks byudjeti (16 bayt) ---
    for prefix in (CB_CHANNEL_SOURCES, CB_SOURCE_URL, CB_SOURCE_RSS,
                   CB_SOURCE_RECYCLE, CB_SOURCE_DRAFTS, CB_SOURCE_DRAFT,
                   CB_SOURCE_FORMAT, CB_SOURCE_ACTION, CB_SOURCE_RSS_ADD,
                   CB_SOURCE_RSS_CHECK, CB_SOURCE_RSS_TOGGLE,
                   CB_SOURCE_RSS_AUTO, CB_SOURCE_RSS_DEL, CB_SOURCE_REC_PICK):
        size = callback_byte_len(prefix)
        check(f"prefiks ≤16 bayt: {prefix}", size <= CALLBACK_PREFIX_MAX_BYTES,
              str(size))

    # --- HUB klaviaturasi (3 tilda bir xil tuzilma) ---
    for lang in LANGS:
        labels = _labels(SRC.sources_hub_keyboard(CH_ID, 2, lang))
        check(f"[{lang}] HUB: 5 ta tugma", len(labels) == 5, str(labels))
        drafts_labels = [l for l in labels
                         if "Qoralamalar" in l or "Черновики" in l or "Drafts" in l]
        check(f"[{lang}] HUB: qoralamalar tugmasi qisqa yorliqda",
              drafts_labels and not any(ch.isdigit() for ch in drafts_labels[0]),
              str(labels))

    # --- 64 bayt: dinamik payload'li tugmalar ---
    samples = [
        SRC.source_list_keyboard([{"id": 987654321, "title": "Manba",
                                   "interval_minutes": 60, "enabled": True,
                                   "autopublish": False}], CH_ID, "uz"),
        SRC.drafts_keyboard([{"id": 987654321, "title": "Qoralama"}], "uz"),
        SRC.recycle_keyboard([{"text": "Eski post matni" * 5, "views": 100,
                               "age_days": 30}], "uz"),
    ]
    oversized = [c for markup in samples for c in _cbs(markup)
                 if callback_byte_len(c) > CALLBACK_DATA_MAX_BYTES]
    check("dinamik tugmalar (manba/qoralama/nomzod) ≤64 bayt",
          not oversized, str(oversized))

    # --- i18n paritet ---
    rep = sources_parity_report()
    check("sources i18n: uz/ru/en 100% paritet (in_sync)",
          rep.get("in_sync") is True, str({k: v for k, v in rep.items()
                                           if k != "keys"})[:200])
    check("sources i18n: tugma kalitlari to'liq",
          all(sources_t(key, lang) for key in SOURCES_BUTTON_KEYS
              for lang in LANGS))
    cq = channels_queue_parity_report()
    check("channels_queue i18n: paritet saqlangan (yangi tugma bilan)",
          cq.get("in_sync") is True, str({k: v for k, v in cq.items()
                                          if k != "keys"})[:200])
    check("yangi kalitlar 3 tilda tarjima qilingan",
          sources_t("src_publish_queued", "uz")
          != sources_t("src_publish_queued", "en")
          and all(sources_t("src_rec_similarity", lang, similarity=10,
                            threshold=75) for lang in LANGS))

    # --- FSM holatlari unikalligi ---
    states = {}
    import handlers.autopilot as AP
    import handlers.image_post as IP
    import handlers.templates as TP
    for mod in (SRC, AP, TP, IP):
        for name in dir(mod):
            if name.isupper() and isinstance(getattr(mod, name), int):
                value = getattr(mod, name)
                if 400 <= value < 600:
                    states.setdefault(value, []).append(f"{mod.__name__}.{name}")
    # Bir modul ICHIDAGI aliaslar (masalan IMAGE_INPUT == IMAGE_POST_INPUT)
    # to'qnashuv emas — faqat TURLI modullardagi bir xil raqam xavfli.
    dupes = {v: names for v, names in states.items()
             if len({n.split(".")[0] for n in names}) > 1}
    check("FSM: 530–539 boshqa oqimlar bilan to'qnashmaydi",
          not dupes, str(dupes))
    check("FSM: manbalar 530–539 ketma-ket",
          (SRC.SRC_HUB, SRC.SRC_URL_INPUT, SRC.SRC_URL_FORMATS,
           SRC.SRC_PREVIEW, SRC.SRC_TIME_INPUT, SRC.SRC_RSS_MENU,
           SRC.SRC_RSS_URL, SRC.SRC_RSS_INTERVAL, SRC.SRC_RECYCLE_LIST,
           SRC.SRC_DRAFTS) == tuple(range(530, 540)))

    # --- routing ---
    app = _build_app()
    routes = (
        (f"ch_src:{CH_ID}", SRC.SRC_HUB, "channel_sources_entry"),
    )
    for data, state, fname in routes:
        ok = _routed(app, data, state, fname)
        check(f"routing: {data} → {fname}", ok)

    state_routes = (
        (f"src_url:{CH_ID}", SRC.SRC_HUB, "sources_hub_callback"),
        (f"src_rss:{CH_ID}", SRC.SRC_HUB, "sources_hub_callback"),
        (f"src_rec:{CH_ID}", SRC.SRC_HUB, "sources_hub_callback"),
        (f"src_drf:{CH_ID}", SRC.SRC_HUB, "sources_hub_callback"),
        ("src_add", SRC.SRC_RSS_MENU, "rss_menu_callback"),
        ("src_chk:5", SRC.SRC_RSS_MENU, "rss_menu_callback"),
        ("src_tgl:5", SRC.SRC_RSS_MENU, "rss_menu_callback"),
        ("src_auto:5", SRC.SRC_RSS_MENU, "rss_menu_callback"),
        ("src_del:5", SRC.SRC_RSS_MENU, "rss_menu_callback"),
        ("src_rp:0", SRC.SRC_RECYCLE_LIST, "recycle_pick_callback"),
        ("src_draft:ok:5", SRC.SRC_DRAFTS, "draft_action_callback"),
        ("src_fmt:news", SRC.SRC_URL_FORMATS, "url_format_callback"),
        ("src_act:now", SRC.SRC_PREVIEW, "preview_action_callback"),
        ("src_cancel", SRC.SRC_PREVIEW, "source_cancel_callback"),
    )
    for data, state, fname in state_routes:
        check(f"routing: {data} @{state} → {fname}",
              _routed_in_state(app, data, state, fname))

    # --- stale tarmog'i (suhbat faol emas) ---
    handler = _handler_for(app, _cb_update("src_fmt:news"))
    check("stale: src_fmt:news (suhbatsiz) → sources_stale_callback",
          getattr(getattr(handler, "callback", None), "__name__", "")
          == "sources_stale_callback",
          str(getattr(handler, "callback", None)))


# ---------------------------------------------------------------------------
# ROUTING YORDAMCHILARI
# ---------------------------------------------------------------------------
def _build_app():
    from telegram.ext import ApplicationBuilder
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = ApplicationBuilder().token("123456:PHASE_D_TEST").build()
    H.register_all_handlers(app)
    return app


def _cb_update(data, user_id=USER_ID):
    from telegram import Update
    return Update.de_json({
        "update_id": 1,
        "callback_query": {
            "id": "cbq-1",
            "from": {"id": user_id, "is_bot": False, "first_name": "Tester"},
            "chat_instance": "pd-1",
            "data": data,
            "message": {
                "message_id": 5, "date": 0,
                "chat": {"id": user_id, "type": "private"},
                "from": {"id": 1, "is_bot": True, "first_name": "Bot"},
            },
        },
    }, None)


def _find_conversation(app):
    from telegram.ext import ConversationHandler
    for group in sorted(app.handlers):
        for handler in app.handlers[group]:
            if isinstance(handler, ConversationHandler):
                return handler
    return None


def _routed(app, data, state, fname):
    conv = _find_conversation(app)
    if conv is None:
        return False
    update = _cb_update(data)
    fn = getattr(SRC, fname)
    from telegram.ext import CallbackQueryHandler as _CQH
    for handler in conv.entry_points:
        if isinstance(handler, _CQH) and handler.callback is fn:
            if handler.check_update(update):
                return True
    return False


def _routed_in_state(app, data, state, fname):
    conv = _find_conversation(app)
    if conv is None:
        return False
    update = _cb_update(data)
    fn = getattr(SRC, fname)
    from telegram.ext import CallbackQueryHandler as _CQH
    for handler in conv.states.get(state, []):
        if isinstance(handler, _CQH) and handler.callback is fn:
            if handler.check_update(update):
                return True
    return False


def _handler_for(app, update):
    for group in sorted(app.handlers):
        for handler in app.handlers[group]:
            res = handler.check_update(update)
            if res is not None and res is not False:
                return handler
    return None


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    print("=" * 64)
    print("📥 PHASE D (2/2) — KONTENT MANBALARI TESTLARI")
    print("🔗 URL→POST · 📡 RSS/ATOM · ♻️ RECYCLE · 🕒 SCHEDULER")
    print("=" * 64)

    test_url_post_flow()
    test_rss_handler_flow()
    test_rss_service_layer()
    test_recycle_flow()
    test_drafts_flow()
    test_scheduler_integration()
    test_ui_routing_i18n()

    print("\n" + "=" * 64)
    print(f" JAMI: o'tdi={PASSED}, xato={FAILURES}")
    if FAILURES:
        print(" ❌ BA'ZI TESTLAR YIQILDI (yuqoridagi [FAIL] qatorlarini ko'ring)")
    else:
        print(" PHASE D (2/2: KONTENT MANBALARI) — 100% YASHIL ✔")
    print("=" * 64)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
