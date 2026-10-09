#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🚪 SPRINT 4 — YOPIQ BETA DARVOZASI TESTI (deterministik).

Tekshiriladi:
  (1) ⚙️ SOZLAMA — ``BETA_INVITE_ONLY`` env orqali o'qiladi (standart
      ``false`` — fail-open), ``BETA_MAX_USERS`` o'rinlar soni;
  (2) 🧠 MANTIQ — qaror sabablari: open_mode / existing_user / admin_access /
      invite_code / admin_approved / pending_approval / invalid_code /
      code_exhausted / beta_full;
  (3) 🎟 KODLAR — yaratish, ishlatilishi (max_uses), o'chirish, normalizatsiya
      (registr/chiziqcha), takroriy kod rad etilishi;
  (4) 👥 NAVBAT — tasdiqlash/rad etish, urinishlar sanogi, o'rinlar hisobi;
  (5) 💾 PERSISTENCE — JSON holat (buzilgan holat xavfsiz), xotira ombori va
      REAL PostgreSQL (``system_settings``) ustida to'liq sikl;
  (6) 🚀 /START INTEGRATSIYASI — haqiqiy ``handlers.start.start`` chaqiriladi:
      eski foydalanuvchi va admin uzluksiz ishlaydi; yangi foydalanuvchi kod
      bilan kiritiladi; kodsiz — navbatga qo'yiladi (javob yuboriladi);
  (7) 🖥 /beta ADMIN BUYRUG'I — holat, kod yaratish, navbat, tasdiq/rad,
      runtime on/off/reset; oddiy foydalanuvchi uchun jim;
  (8) 📄 HUJJAT — ``.env.example`` (yagona kanonik nusxa) yangi kalitlarni
      saqlaydi.
"""
import asyncio
import contextlib
import json
import os
import sys
import subprocess
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BOT = os.path.join(ROOT, "telegram_bot")
if BOT not in sys.path:
    sys.path.insert(0, BOT)

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("BOT_TOKEN", "123456:BETA_GATE_TEST")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test")

PASSED = 0
FAILED = 0
ADMIN_ID = 123456789          # config.ADMIN_ID → admin
NEW_USER = 900001             # yangi foydalanuvchi (kod/approval kerak)
OLD_USER = 900002             # eski foydalanuvchi (beta'gacha)
LANGS = ("uz", "ru", "en")


def check(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  [OK] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} {detail}")
    return bool(condition)


def _gate(invite_only=True, max_users=50, **kwargs):
    """Xotira omborli darvoza (bazasiz, deterministik)."""
    from services import beta_gate as bg

    store = bg.MemoryBetaStore()
    gate = bg.BetaGate(store, invite_only=invite_only, max_users=max_users, **kwargs)
    return gate, store


# ---------------------------------------------------------------------------
# 1) Sozlama (env → config)
# ---------------------------------------------------------------------------
def test_config_env():
    print("\n== TEST 1: BETA_INVITE_ONLY / BETA_MAX_USERS (env) ==")
    env = dict(os.environ)
    env["PYTHONPATH"] = BOT
    code = (
        "import config; "
        "print(config.BETA_INVITE_ONLY, config.BETA_MAX_USERS, config.USD_UZS_RATE)"
    )
    default = subprocess.run([sys.executable, "-c", code], env=env,
                             capture_output=True, text=True)
    check("standart rejim: BETA_INVITE_ONLY = False (ochiq)",
          default.stdout.strip().startswith("False"), default.stdout)

    env_on = dict(env)
    env_on.update({"BETA_INVITE_ONLY": "true", "BETA_MAX_USERS": "37",
                   "USD_UZS_RATE": "13000"})
    enabled = subprocess.run([sys.executable, "-c", code], env=env_on,
                             capture_output=True, text=True)
    check("env=true → rejim YOQILADI, o'rinlar 37, kurs 13000",
          enabled.stdout.strip() == "True 37 13000", enabled.stdout)

    env_bad = dict(env)
    env_bad["BETA_INVITE_ONLY"] = "maybe"
    weird = subprocess.run([sys.executable, "-c", code], env=env_bad,
                           capture_output=True, text=True)
    check("noto'g'ri qiymat → ochiq rejim (fail-safe)", weird.stdout.startswith("False"),
          weird.stdout)


# ---------------------------------------------------------------------------
# 2-4) Mantiq, kodlar, navbat
# ---------------------------------------------------------------------------
def test_decision_logic():
    print("\n== TEST 2: Qaror mantiqi (sabablar) ==")
    from services import beta_gate as bg

    # (a) Darvoza o'chiq — hamma o'tadi, holat O'QILMAYDI ham.
    closed_store = bg.MemoryBetaStore()
    closed_store.set_failing(True)  # ombor ishlamaydi — baribir ochiq
    open_gate = bg.BetaGate(closed_store, invite_only=False)
    decision = open_gate.check(NEW_USER, is_new=True)
    check("ochiq rejim: yangi foydalanuvchi o'tadi (store o'qilmaydi)",
          decision["allowed"] and decision["reason"] == bg.REASON_OPEN, decision)

    gate, _store = _gate()

    d = gate.check(OLD_USER, is_new=False)
    check("eski foydalanuvchi: uzluksiz o'tadi (existing_user)",
          d["allowed"] and d["reason"] == bg.REASON_EXISTING, d)

    d = gate.check(ADMIN_ID, is_new=True, is_admin=True)
    check("admin: har doim o'tadi (admin_access)",
          d["allowed"] and d["reason"] == bg.REASON_ADMIN, d)

    d = gate.check(NEW_USER, is_new=True)
    check("yangi foydalanuvchi kodsiz: navbatga (pending_approval)",
          (not d["allowed"]) and d["reason"] == bg.REASON_PENDING, d)
    check("navbat yozuvi yaratildi (user_id + urinishlar)",
          str(NEW_USER) in gate.pending_users()
          and gate.pending_users()[str(NEW_USER)]["attempts"] == 1,
          gate.pending_users())
    check("o'rinlar hisobi: 0/50 band", gate.status()["seats_used"] == 0)

    d = gate.check(NEW_USER, is_new=True, invite_code="BETA-YOQ")
    check("noto'g'ri kod: invalid_code", d["reason"] == bg.REASON_INVALID_CODE, d)
    check("takroriy urinish urinishlar sonini oshiradi",
          gate.pending_users()[str(NEW_USER)]["attempts"] == 2)

    # (b) To'g'ri kod — kiritiladi va kod "sarflanadi".
    created = gate.add_code("BETA-OPEN", max_uses=2, created_by=ADMIN_ID,
                            note="test")
    check("kod yaratildi (normalizatsiya)", created["code"] == "BETA-OPEN", created)
    d = gate.check(NEW_USER, is_new=True, invite_code="beta-open")
    check("to'g'ri kod: kiritildi (invite_code)",
          d["allowed"] and d["reason"] == bg.REASON_INVITE, d)
    check("kod ishlatilishi oshdi (uses=1)",
          gate.list_codes()["BETA-OPEN"]["uses"] == 1)
    check("navbatdan olib tashlandi", str(NEW_USER) not in gate.pending_users())
    check("o'rin band bo'ldi (1/50)", gate.status()["seats_used"] == 1)

    d = gate.check(NEW_USER, is_new=False)
    check("kiritilgan foydalanuvchi keyingi /start'da o'tadi (approved)",
          d["allowed"] and d["reason"] == bg.REASON_APPROVED, d)

    # (c) Kod tugadi.
    gate.check(700001, is_new=True, invite_code="BETA-OPEN")
    d = gate.check(700002, is_new=True, invite_code="BETA-OPEN")
    check("kod limiti tugadi: code_exhausted",
          d["reason"] == bg.REASON_CODE_EXHAUSTED, d)

    # (d) O'rinlar tugadi.
    full_gate, _ = _gate(max_users=1)
    full_gate.approve(800001, approved_by=ADMIN_ID)
    full_gate.add_code("BETA-ANY", max_uses=5)
    d = full_gate.check(800002, is_new=True, invite_code="BETA-ANY")
    check("o'rinlar to'lgan: beta_full", d["reason"] == bg.REASON_BETA_FULL, d)
    check("kodsiz ham beta_full",
          full_gate.check(800003, is_new=True)["reason"] == bg.REASON_BETA_FULL)
    check("max_users=0 — cheksiz",
          _gate(max_users=0)[0].status()["seats_left"] is None)


def test_admin_flow():
    print("\n== TEST 3: Admin tasdiq/rad + runtime rejim ==")
    from services import beta_gate as bg

    gate, _store = _gate()
    gate.check(NEW_USER, is_new=True)           # navbatga qo'yildi
    check("navbatda 1 ta so'rov", gate.status()["pending"] == 1)

    check("approve() natijasi True",
          gate.approve(NEW_USER, approved_by=ADMIN_ID, source="admin") is True)
    check("tasdiqlangan foydalanuvchi o'tadi",
          gate.check(NEW_USER, is_new=True)["allowed"] is True)
    check("navbat bo'shadi", gate.status()["pending"] == 0)
    check("tasdiq meta (kim/qachon)",
          gate.approved_users()[str(NEW_USER)]["approved_by"] == ADMIN_ID)

    # Rad etish — faqat navbatdagilar uchun.
    gate.check(910001, is_new=True)
    check("rad etish navbatdagini o'chiradi",
          gate.reject(910001, reason="spam") is True
          and not gate.reject(910001))
    check("rad etilgan foydalanuvchi YANA so'rashi mumkin (qora ro'yxat emas)",
          gate.check(910001, is_new=True)["reason"] == bg.REASON_PENDING)

    # Kodlar boshqaruvi.
    gate.add_code("BETA-ONE", max_uses=1)
    check("dublikat kod rad etiladi", gate.add_code("BETA-ONE") is None)
    check("kod normalizatsiya bilan topiladi (betaone)",
          gate.find_code("betaone")[0] == "BETA-ONE")
    check("kod o'chirish", gate.revoke_code("beta-one") is True
          and gate.find_code("BETA-ONE")[0] is None)
    check("yo'q kodni o'chirish False", gate.revoke_code("BETA-YOQ") is False)
    check("kod ishlatilishi 0 dan boshlanadi",
          gate.add_code("BETA-TWO")["uses"] == 0)

    # Runtime rejim (konstruktor override'i YO'Q — holat/env boshqaradi).
    rt, _rt_store = _gate(invite_only=None)
    check("runtime: yoqish (holat override)",
          rt.set_enabled(True) is True and rt.invite_only is True)
    check("yoqilganda yangi foydalanuvchi to'xtatiladi",
          rt.check(920001, is_new=True)["reason"] == bg.REASON_PENDING)
    check("runtime: o'chirish", rt.set_enabled(False) is True and rt.invite_only is False)
    check("o'chirilganda yangi foydalanuvchi o'tadi",
          rt.check(920002, is_new=True)["allowed"] is True)
    check("runtime manbasi statusda ko'rinadi (override)",
          rt.status()["enabled_source"] == "override")
    check("env'ga qaytarish (None) → test env ochiq",
          rt.set_enabled(None) is True and rt.invite_only is False)

    # Kod generatsiyasi.
    code = bg.generate_code(seed=42)
    check("kod formati BETA-XXXXXX",
          code.startswith("BETA-") and len(code) == 11, code)
    check("generatsiya seed bilan deterministik",
          bg.generate_code(seed=42) == code)
    check("normalizatsiya: bo'shliq/chiziqcha",
          bg.normalize_code(" beta - a1b2 ") == "BETA-A1B2", bg.normalize_code(" beta - a1b2 "))


def test_state_persistence_helpers():
    print("\n== TEST 4: Holat JSON'i (xavfsiz o'qish) ==")
    from services import beta_gate as bg

    state = bg.empty_state()
    state["codes"]["BETA-X"] = {"max_uses": 3, "uses": 1}
    raw = bg.serialize_state(state)
    parsed = bg.parse_state(raw)
    check("serialize → parse: kodlar saqlanadi",
          parsed["codes"]["BETA-X"]["max_uses"] == 3)
    check("buzilgan JSON → bo'sh holat (crash yo'q)",
          bg.parse_state("{buzilgan") == bg.empty_state())
    check("None → bo'sh holat", bg.parse_state(None) == bg.empty_state())
    check("enabled=True saqlanadi", bg.parse_state('{"enabled": true}')["enabled"] is True)
    check("noma'lum kalitlar e'tiborsiz",
          set(bg.parse_state('{"version":1,"hack":[]}')) == set(bg.empty_state()))

    store = bg.MemoryBetaStore()
    store.save(bg.parse_state('{"codes": {"A": {"uses": 0, "max_uses": 1}}}'))
    check("xotira ombori round-trip", store.load()["codes"]["A"]["uses"] == 0)


# ---------------------------------------------------------------------------
# 5) LIVE: system_settings orqali persistence
# ---------------------------------------------------------------------------
def test_live_settings_store():
    print("\n== TEST 5: Real PostgreSQL (system_settings) ==")
    try:
        import pgserver  # noqa: F401
    except ImportError:
        print("  [SKIP] pgserver yo'q — live DB qismi o'tkazib yuborildi")
        return
    import shutil
    import tempfile

    import database as db
    from services import beta_gate as bg

    server_dir = os.path.join(tempfile.gettempdir(), "yordamchi_pg_beta")
    shutil.rmtree(server_dir, ignore_errors=True)
    server = pgserver.get_server(server_dir)
    uri = server.get_uri()
    os.environ["DATABASE_URL"] = uri
    db.DATABASE_URL = uri
    db._reset_pool()
    db.init_db()

    store = bg.SettingsBetaStore(db)
    gate = bg.BetaGate(store, invite_only=True, max_users=3)
    gate.add_code("BETA-DB", max_uses=1, created_by=ADMIN_ID)

    # Yangi darvoza (jarayon qayta ishga tushgani kabi) — holat bazadan.
    gate2 = bg.BetaGate(store, invite_only=True, max_users=3)
    check("bazadan o'qish: kod saqlanib qolgan",
          "BETA-DB" in gate2.list_codes(), gate2.list_codes())

    decision = gate2.check(NEW_USER, is_new=True, invite_code="BETA-DB")
    check("baza orqali kod kiritildi", decision["allowed"] is True, decision)

    gate3 = bg.BetaGate(store, invite_only=True, max_users=3)
    check("tasdiq bazada saqlanadi (qayta o'qishda ham)",
          gate3.check(NEW_USER, is_new=False)["allowed"] is True)
    check("o'rinlar bazadan hisoblanadi (1/3)",
          gate3.status()["seats_used"] == 1, gate3.status())

    gate3.check(930001, is_new=True)     # navbatga
    check("navbat bazada saqlanadi",
          "930001" in bg.BetaGate(store, invite_only=True).pending_users())

    check("kod bir marta ishlatiladi (ikkinchi urinish rad)",
          bg.BetaGate(store, invite_only=True).check(
              930002, is_new=True, invite_code="BETA-DB")["reason"]
          == bg.REASON_CODE_EXHAUSTED)

    # system_settings kaliti haqiqatan ishlatilgan.
    raw = db.get_setting(bg.BETA_STATE_KEY, "")
    parsed = json.loads(raw or "{}")
    check("system_settings'da beta_gate_state JSON yozuvi bor",
          "codes" in parsed and "approved" in parsed, list(parsed))

    db.close_pool()


# ---------------------------------------------------------------------------
# 6) /start integratsiyasi
# ---------------------------------------------------------------------------
class _Msg:
    def __init__(self, text=None):
        self.text = text
        self.sent = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.sent.append(dict(text=text, reply_markup=reply_markup))
        return self


class _Bot:
    async def send_message(self, *a, **kw):
        return True


@contextlib.contextmanager
def _patched_start(gate, *, is_new=True, save_calls=None):
    """``handlers.start.start`` ni deterministik muhitda chaqirish uchun patch."""
    import database as db_mod
    import importlib

    start_mod = importlib.import_module("handlers.start")
    from repositories.users_repository import _UserSaveResult

    original = {
        "run_db": db_mod.run_db,
        "peek_profile": start_mod.peek_profile,
        "check_user_subscribed": start_mod.check_user_subscribed,
        "get_smart_reply_ad_async": start_mod.get_smart_reply_ad_async,
        "resolve_main_keyboard": start_mod.resolve_main_keyboard,
        "main_menu_intro_suffix": start_mod.main_menu_intro_suffix,
        "run_background_task": start_mod.run_background_task,
    }

    async def _fake_run_db(func, *args, **kwargs):
        name = getattr(func, "__name__", "")
        if name == "save_user":
            if save_calls is not None:
                save_calls.append(args[0] if args else kwargs.get("user_id"))
            return _UserSaveResult(is_new=is_new, lang="uz")
        if name == "get_user_language":
            return "uz"
        return {}

    async def _subscribed(bot, user_id):
        return True, []

    async def _no_ad(user_id):
        return ""

    async def _no_markup(*a, **kw):
        return None

    async def _no_suffix(*a, **kw):
        return ""

    background = []

    def _bg(coro, **kw):
        background.append(kw.get("name"))
        try:
            coro.close()
        except Exception:
            pass
        return None

    db_mod.run_db = _fake_run_db
    start_mod.peek_profile = lambda uid: None
    start_mod.check_user_subscribed = _subscribed
    start_mod.get_smart_reply_ad_async = _no_ad
    start_mod.resolve_main_keyboard = _no_markup
    start_mod.main_menu_intro_suffix = _no_suffix
    start_mod.run_background_task = _bg
    try:
        yield SimpleNamespace(background=background)
    finally:
        db_mod.run_db = original["run_db"]
        start_mod.peek_profile = original["peek_profile"]
        start_mod.check_user_subscribed = original["check_user_subscribed"]
        start_mod.get_smart_reply_ad_async = original["get_smart_reply_ad_async"]
        start_mod.resolve_main_keyboard = original["resolve_main_keyboard"]
        start_mod.main_menu_intro_suffix = original["main_menu_intro_suffix"]
        start_mod.run_background_task = original["run_background_task"]


def _start_ctx(args=None, lang="uz"):
    return SimpleNamespace(args=list(args or []), user_data={"lang": lang},
                           chat_data={}, bot=_Bot(), application=None)


def _start_update(user_id, first_name="Tester"):
    msg = _Msg()
    return SimpleNamespace(
        message=msg, effective_message=msg, callback_query=None,
        effective_user=SimpleNamespace(id=user_id, first_name=first_name,
                                       username="tester", full_name="Tester T."),
    ), msg


def test_start_integration():
    print("\n== TEST 6: /start integratsiyasi (haqiqiy handler) ==")
    import importlib

    start_mod = importlib.import_module("handlers.start")
    beta_mod = importlib.import_module("handlers.beta_access")
    from services import beta_gate as bg

    # (a) Darvoza O'CHIQ — hech narsa o'zgarmaydi (regressiya yo'q).
    open_gate = bg.BetaGate(bg.MemoryBetaStore(), invite_only=False)
    gate, _store = _gate()
    # ``/start`` ichida ``gate_service.default_gate()`` chaqiriladi — jarayon
    # bo'yicha darvoza o'rniga test darvozasini beramiz.
    current = {"gate": open_gate}
    original_default_gate = bg.default_gate
    bg.default_gate = lambda: current["gate"]
    saved = []
    notified = []
    original_notify = beta_mod.notify_admins_about_request
    original_bg = beta_mod.run_background_task

    async def _fake_notify(context, user, decision):
        notified.append((user.id, decision.get("reason")))

    def _fake_bg(coro, **kw):
        try:
            coro.close()
        except Exception:
            pass
        return None

    beta_mod.notify_admins_about_request = _fake_notify
    beta_mod.run_background_task = _fake_bg
    try:
        with _patched_start(open_gate, save_calls=saved):
            upd, msg = _start_update(NEW_USER)
            asyncio.run(start_mod.start(upd, _start_ctx()))
        check("ochiq rejim: foydalanuvchi saqlandi (save_user chaqirildi)",
              saved == [NEW_USER], saved)
        check("ochiq rejim: salomlashish yuborildi", bool(msg.sent))

        # (b) Darvoza YOQILGAN — kodsiz yangi foydalanuvchi to'xtatiladi.
        current["gate"] = gate
        with _patched_start(gate, save_calls=saved):
            upd, msg = _start_update(NEW_USER)
            asyncio.run(start_mod.start(upd, _start_ctx()))
        check("yangi foydalanuvchi (kodsiz): javob yuborildi", bool(msg.sent))
        user_text = msg.sent[-1]["text"] if msg.sent else ""
        check("javobda beta matni bor (beta_pending)",
              "beta" in user_text.lower() or "🚪" in user_text, user_text[:60])
        check("navbatga qo'yildi", str(NEW_USER) in gate.pending_users())

        # (c) Xuddi shu foydalanuvchi TO'G'RI kod bilan kiradi.
        gate.add_code("BETA-777", max_uses=1, created_by=ADMIN_ID)
        saved = []
        with _patched_start(gate, save_calls=saved):
            upd, msg = _start_update(NEW_USER)
            asyncio.run(start_mod.start(upd, _start_ctx(args=["BETA-777"])))
        check("kod bilan: foydalanuvchi ro'yxatdan o'tdi (save_user)",
              saved == [NEW_USER], saved)
        greeting = msg.sent[-1]["text"] if msg.sent else ""
        check("kod qabul qilingani matnda ko'rinadi",
              "✅" in greeting or "beta" in greeting.lower(), greeting[:60])
        check("kod sarflandi (uses=1)", gate.list_codes()["BETA-777"]["uses"] == 1)

        # (d) Eski foydalanuvchi — hech qanday to'siqsiz.
        saved = []
        with _patched_start(gate, is_new=False, save_calls=saved):
            upd, msg = _start_update(OLD_USER)
            asyncio.run(start_mod.start(upd, _start_ctx()))
        check("eski foydalanuvchi: to'siqsiz o'tadi (saved)",
              saved == [OLD_USER] and bool(msg.sent), saved)

        # (e) Admin — kod talab qilinmaydi.
        saved = []
        with _patched_start(gate, save_calls=saved):
            upd, msg = _start_update(ADMIN_ID)
            asyncio.run(start_mod.start(upd, _start_ctx()))
        check("admin: kod talab qilinmaydi", bool(msg.sent))

        # (f) `ref_<id>` bilan birga kelgan kod ham taniladi.
        gate.add_code("BETA-REF", max_uses=1)
        saved = []
        with _patched_start(gate, save_calls=saved):
            upd, msg = _start_update(700123)
            asyncio.run(start_mod.start(upd, _start_ctx(args=["ref_1", "BETA-REF"])))
        check("ref_ + kod birga: kod ishlatildi",
              saved == [700123] and gate.list_codes()["BETA-REF"]["uses"] == 1)
    finally:
        beta_mod.notify_admins_about_request = original_notify
        beta_mod.run_background_task = original_bg
        bg.default_gate = original_default_gate


# ---------------------------------------------------------------------------
# 7) /beta admin buyrug'i + registratsiya
# ---------------------------------------------------------------------------
def test_beta_command():
    print("\n== TEST 7: /beta buyrug'i ==")
    import database as db_mod
    import importlib

    beta_mod = importlib.import_module("handlers.beta_access")
    from services import beta_gate as bg

    gate, _store = _gate(invite_only=None)   # runtime override erkin
    original_default = bg.default_gate
    original_bg = beta_mod.run_background_task
    bg.default_gate = lambda: gate

    def _fake_bg(coro, **kw):
        try:
            coro.close()
        except Exception:
            pass
        return None

    beta_mod.run_background_task = _fake_bg
    try:
        ctx = _start_ctx()
        upd, msg = _start_update(ADMIN_ID)
        asyncio.run(beta_mod.beta_admin_command(upd, ctx))
        status = msg.sent[-1]["text"] if msg.sent else ""
        check("/beta — holat ekrani chiqadi", "beta" in status.lower(), status[:60])

        upd, msg = _start_update(ADMIN_ID)
        asyncio.run(beta_mod.beta_admin_command(
            upd, _start_ctx(args=["code", "BETA-MANUAL", "3", "izoh"])))
        check("/beta code — kod yaratildi",
              gate.list_codes().get("BETA-MANUAL", {}).get("max_uses") == 3,
              gate.list_codes())
        created_msg = msg.sent[-1]["text"] if msg.sent else ""
        check("/beta code — tasdiq matni", "BETA-MANUAL" in created_msg, created_msg[:80])

        upd, msg = _start_update(ADMIN_ID)
        asyncio.run(beta_mod.beta_admin_command(upd, _start_ctx(args=["codes"])))
        check("/beta codes — ro'yxat", "BETA-MANUAL" in (msg.sent[-1]["text"] if msg.sent else ""))

        gate.set_enabled(True)   # navbat qarorlari uchun rejim YOQILGAN
        check("rejim yondi (navbat testi uchun)", gate.invite_only is True)
        gate.check(950001, is_new=True)   # navbatga
        upd, msg = _start_update(ADMIN_ID)
        asyncio.run(beta_mod.beta_admin_command(upd, _start_ctx(args=["pending"])))
        pending_text = msg.sent[-1]["text"] if msg.sent else ""
        check("/beta pending — user_id ko'rinadi", "950001" in pending_text, pending_text[:80])

        upd, msg = _start_update(ADMIN_ID)
        asyncio.run(beta_mod.beta_admin_command(
            upd, _start_ctx(args=["approve", "950001"])))
        check("/beta approve — foydalanuvchi qabul qilindi",
              gate.check(950001, is_new=True)["allowed"] is True,
              gate.approved_users())
        check("/beta approve — tasdiq matni",
              "950001" in (msg.sent[-1]["text"] if msg.sent else ""))

        upd, msg = _start_update(ADMIN_ID)
        asyncio.run(beta_mod.beta_admin_command(
            upd, _start_ctx(args=["reject", "950001"])))
        check("/beta reject — navbatda yo'q (xabar jim)", bool(msg.sent))

        upd, msg = _start_update(ADMIN_ID)
        asyncio.run(beta_mod.beta_admin_command(upd, _start_ctx(args=["on"])))
        check("/beta on — rejim yondi", gate.invite_only is True)
        upd, msg = _start_update(ADMIN_ID)
        asyncio.run(beta_mod.beta_admin_command(upd, _start_ctx(args=["off"])))
        check("/beta off — rejim o'chdi", gate.invite_only is False)
        check("/beta off — yangi foydalanuvchi o'tadi",
              gate.check(960001, is_new=True)["allowed"] is True)
        upd, msg = _start_update(ADMIN_ID)
        asyncio.run(beta_mod.beta_admin_command(upd, _start_ctx(args=["reset"])))
        check("/beta reset — env qiymatiga qaytdi (test env: ochiq)",
              gate.invite_only is False and gate.status()["enabled_source"] == "env")

        # Oddiy foydalanuvchi — jim (javob yo'q, holat o'zgarmaydi).
        upd, msg = _start_update(NEW_USER)
        asyncio.run(beta_mod.beta_admin_command(upd, _start_ctx(args=["code", "BETA-HACK"])))
        check("oddiy foydalanuvchi /beta — javob YO'Q va kod yaratilmadi",
              not msg.sent and "BETA-HACK" not in gate.list_codes())
    finally:
        bg.default_gate = original_default
        beta_mod.run_background_task = original_bg


def test_registration_and_docs():
    print("\n== TEST 8: Registratsiya va hujjat ==")
    from telegram.ext import ApplicationBuilder, CommandHandler
    import handlers

    app = ApplicationBuilder().token(os.environ["BOT_TOKEN"]).build()
    handlers.register_all_handlers(app)
    commands = set()
    for h in app.handlers.get(0, []):
        if isinstance(h, CommandHandler):
            commands.update(h.commands)
    check("CommandHandler('beta') ro'yxatdan o'tgan", "beta" in commands,
          sorted(commands))

    # Hujjat: yagona kanonik .env.example yangi kalitlarni saqlaydi.
    for path in (os.path.join(ROOT, ".env.example"),):
        text = open(path, encoding="utf-8").read()
        check(f"{os.path.relpath(path, ROOT)}: BETA_INVITE_ONLY=false",
              "BETA_INVITE_ONLY=false" in text)
        check(f"{os.path.relpath(path, ROOT)}: BETA_MAX_USERS=50",
              "BETA_MAX_USERS=50" in text)
        check(f"{os.path.relpath(path, ROOT)}: USD_UZS_RATE mavjud",
              "USD_UZS_RATE=" in text)
        check(f"{os.path.relpath(path, ROOT)}: /beta buyrug'i izohlangan",
              "/beta" in text)


def main():
    print("=" * 70)
    print(" 🚪 SPRINT 4 — YOPIQ BETA DARVOZASI (closed beta access)")
    print("=" * 70)
    test_config_env()
    test_decision_logic()
    test_admin_flow()
    test_state_persistence_helpers()
    test_live_settings_store()
    test_start_integration()
    test_beta_command()
    test_registration_and_docs()
    print("\n" + "=" * 70)
    print(f" JAMI: o'tdi={PASSED}, xato={FAILED}")
    if FAILED:
        print(" [FAIL] BETA GATE TESTLARIDA XATOLIK BOR ✘")
        return 1
    print(" SPRINT 4 — BETA GATE 100% YASHIL ✔")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # pragma: no cover
        print(f"\n❌ TEST XATOLIK BILAN YIQILDI: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
