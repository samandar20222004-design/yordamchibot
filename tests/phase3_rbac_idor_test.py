#!/usr/bin/env python3
"""PHASE 3 — RBAC MARKAZLASHUVI va IDOR HIMOYASI (acceptance testlari).

Qamrov (topshiriq bandlari bilan birma-bir)
-------------------------------------------
  TEST 1:  🎭 RESURS ROLLARI — OWNER | EDITOR | SCHEDULER | ANALYST va ularning
           ruxsat matritsasi (``services/rbac_service.py``).
  TEST 2:  🎯 MARKAZIY ``can()`` — ``await rbac_service.can(user_id=...,
           resource_type=..., resource_id=..., action=...)`` barcha rollar
           uchun TO'G'RI javob beradi; noma'lum amal/resurs → fail-closed.
  TEST 3:  🧩 POST RESURSI — ``resource_type="post"`` post orqali kanalni
           aniqlaydi; mavjud bo'lmagan post → rad (IDOR).
  TEST 4:  🛡 MIDDLEWARE QATLAMI — ``parse_resource_id`` (payload validatsiyasi),
           ``enforce_resource_access`` (Permission Denied alert),
           ``resource_guard`` dekoratori, ``ResourceRBACMiddleware``
           (ruxsatsiz callback zanjirdan chiqariladi).
  TEST 5:  ✍️ MANUAL POST IDOR — begona kanal ID'si bilan ``_publish`` →
           DB'ga YOZILMAYDI (``add_post`` chaqirilmaydi) va "Permission Denied".
           Egasi uchun oqim o'zgarmagan (regressiya yo'q).
  TEST 6:  📢 KANALLAR IDOR — ``ch_del:`` (uzish), ``set_style:`` (uslub),
           ``ch_voice:`` (AI tahlil → profil yozish) begona kanal uchun DB'ni
           o'zgartirmaydi.
  TEST 7:  🚀 AVTOPILOT IDOR — begona kanal uchun kirish va navbatga yozish
           (``schedule_autopilot_week``) bloklanadi; egasi uchun ishlaydi.
  TEST 8:  👥 TEAM APPROVAL IDOR — soxta ``team_ok:/team_no:/team_edit:``
           payload'i bilan boshqa post tasdiqlanmaydi/tahrirlanmaydi.
  TEST 9:  🗑 NAVBAT IDOR — begona (yoki mavjud bo'lmagan) post
           ``qdel:`` bilan o'chirilmaydi.
  TEST 10: 🔐 ADMIN CALLBACK QATLAMI — mavjud (6-bosqich) himoya buzilmagan:
           payload ID qat'iy validatsiya + server-side admin tekshiruvi.
  TEST 11: 🔌 MAIN.PY INTEGRATSIYASI — ``ResourceRBACMiddleware`` alohida
           guruhda (-2) ro'yxatga olinadi; haqiqiy PTB zanjirida ruxsatsiz
           callback handler'ga YETIB BORMAYDI (ApplicationHandlerStop).

Ishga tushirish
--------------
    python3 tests/phase3_rbac_idor_test.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

# Test chiqishi toza bo'lsin: RBAC rad etishlari WARNING loglari va DB pool
# xatolari (test muhitida baza yo'q) konsolni to'ldirmasin.  Audit izi
# ``rbac_service.recent_denials()`` orqali ALOHIDA tekshiriladi.
logging.disable(logging.CRITICAL)

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("BOT_TOKEN", "123456:PHASE3_RBAC_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

from telegram.ext import (  # noqa: E402
    ApplicationHandlerStop,
    BaseHandler,
    ConversationHandler,
)

import database as db_mod  # noqa: E402
from services import rbac_service as R  # noqa: E402

OWNER_ID = 900001
EDITOR_ID = 900002
SCHEDULER_ID = 900003
ANALYST_ID = 900004
OUTSIDER_ID = 900005
ADMIN_USER_ID = 123456789

CH_ID = "-1001234567890"
OTHER_CH_ID = "-1009999999999"
POST_ID = 501
FOREIGN_POST_ID = 502

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


def header(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


# ============================================================================
# 0) SOXTA DB — handler'lar ham, RBAC ham AYNAN shu qatlamdan o'tadi
#    (``database.run_db`` — handlerlar ishlatadigan yagona DB eshigi).
# ============================================================================
class FakeDB:
    """Deterministik DB adapteri.

    ``bindings`` — funksiya nomi → qaytariladigan qiymat.  Noma'lum funksiya
    chaqirilsa ``None`` (fail-safe) va jurnalga yoziladi.
    """

    def __init__(self):
        self.owners = {CH_ID: OWNER_ID}
        self.members = {
            (CH_ID, EDITOR_ID): (1, CH_ID, EDITOR_ID, "editor", None),
            (CH_ID, SCHEDULER_ID): (2, CH_ID, SCHEDULER_ID, "scheduler", None),
            (CH_ID, ANALYST_ID): (3, CH_ID, ANALYST_ID, "analyst", None),
        }
        self.posts = {
            POST_ID: {"id": POST_ID, "user_id": OWNER_ID, "channel_id": CH_ID},
            FOREIGN_POST_ID: {"id": FOREIGN_POST_ID, "user_id": 900999,
                              "channel_id": OTHER_CH_ID},
        }
        self.channels = {OWNER_ID: [(CH_ID, "Eganing kanali", "friendly")]}
        self.calls = []
        self.writes = []
        # Navbat ro'yxati bo'sh — o'chirishdan keyin "bo'sh ekran" chiziladi
        # (handler to'liq qator formatini talab qiladi, bu yerda u muhim emas).
        self.queue_posts = []
        self.original = None

    # -- adapter interfeysi -------------------------------------------------
    async def run_db(self, fn, *args, **kwargs):
        name = getattr(fn, "__name__", str(fn))
        self.calls.append((name, args, tuple(sorted(kwargs.items()))))
        if name == "get_user_channels_with_tone":
            return list(self.channels.get(args[0], []))
        if name == "get_user_channels":
            return [(c[0], c[1]) for c in self.channels.get(args[0], [])]
        if name == "get_channel_member":
            return self.members.get((str(args[0]), int(args[1])))
        if name == "get_channel_owner_id":
            return self.owners.get(str(args[0]))
        if name == "get_workflow_post":
            return self.posts.get(int(args[0]))
        if name == "add_post":
            self.writes.append(("add_post", dict(kwargs)))
            return 777
        if name == "set_channel_tone":
            self.writes.append(("set_channel_tone", args))
            return True
        if name == "remove_channel":
            self.writes.append(("remove_channel", args))
            return True
        if name == "get_channel_posts_history":
            return [{"text": "Eski post matni " * 4}]
        if name == "set_channel_tone":
            return True
        if name == "get_queue_post_detail":
            pid, uid = int(args[0]), int(args[1])
            if pid == POST_ID and uid == OWNER_ID:
                return (POST_ID, uid, CH_ID, "text", "Matn", None, None, None,
                        None, False, 0, None, None)
            return None
        if name == "cancel_post":
            self.writes.append(("cancel_post", args))
            return True
        if name == "get_queue_post_count":
            return len(self.queue_posts)
        if name == "get_queue_posts":
            return list(self.queue_posts)
        return None

    # -- patch boshqaruvi ---------------------------------------------------
    def __enter__(self):
        self.original = db_mod.run_db
        db_mod.run_db = self.run_db
        R.invalidate_resource_cache()
        R.clear_denial_log()
        return self

    def __exit__(self, *exc):
        db_mod.run_db = self.original
        R.invalidate_resource_cache()
        return False

    def calls_of(self, name):
        return [c for c in self.calls if c[0] == name]

    def wrote(self, name):
        return [w for w in self.writes if w[0] == name]


# ============================================================================
# 1) RESURS ROLLARI VA MATRITSA
# ============================================================================
def test_resource_roles():
    header("TEST 1: 🎭 Resurs rollari va ruxsat matritsasi")
    check("rollar: OWNER|EDITOR|SCHEDULER|ANALYST",
          R.RESOURCE_ROLES == ("owner", "editor", "scheduler", "analyst"),
          str(R.RESOURCE_ROLES))
    check("ResourceRole enum qiymatlari",
          [r.value for r in (R.ResourceRole.OWNER, R.ResourceRole.EDITOR,
                             R.ResourceRole.SCHEDULER, R.ResourceRole.ANALYST)]
          == ["owner", "editor", "scheduler", "analyst"])
    check("alias parse: 'muharrir' → editor",
          R.parse_resource_role("muharrir") == "editor")
    check("noma'lum rol → None", R.parse_resource_role("superhacker") is None)

    owner_perms = R.resource_role_permissions("owner")
    check("owner: barcha amallar",
          {"view", "view_analytics", "create", "edit", "approve", "reject",
           "schedule", "publish", "manage_members"} <= owner_perms,
          str(sorted(owner_perms)))
    check("editor: create/edit/approve bor, schedule yo'q",
          {"create", "edit", "approve", "reject"} <= R.resource_role_permissions("editor")
          and "schedule" not in R.resource_role_permissions("editor"))
    check("scheduler: faqat schedule (+view)",
          R.resource_role_permissions("scheduler") == frozenset({"view", "schedule"}),
          str(sorted(R.resource_role_permissions("scheduler"))))
    check("analyst: faqat view_analytics (+view)",
          R.resource_role_permissions("analyst") == frozenset({"view", "view_analytics"}))
    check("noma'lum rol → bo'sh to'plam",
          R.resource_role_permissions("hacker") == frozenset())

    # team.py (Phase E) matritsasi bilan izchillik: ish oqimi ruxsatlari
    # markaziy matritsada HAM mavjud (regressiya qo'riqchisi).
    from services.channels.team import ROLE_PERMISSIONS as TEAM_MATRIX
    mismatch = {role: sorted(perms - R.resource_role_permissions(role))
                for role, perms in TEAM_MATRIX.items()
                if perms - R.resource_role_permissions(role)}
    check("markaziy matritsa team.py ish oqimi ruxsatlarini qamraydi",
          not mismatch, str(mismatch))

    check("amal aliaslari: approve_post → approve",
          R.permission_for_action("approve_post") == "approve")
    check("amal aliaslari: statistics → view_analytics",
          R.permission_for_action("statistics") == "view_analytics")
    check("noma'lum amal → None", R.permission_for_action("hack") is None)


# ============================================================================
# 2) MARKAZIY can() — ASYNC TEKSHIRUV NUQTASI
# ============================================================================
def test_central_can():
    header("TEST 2: 🎯 Markaziy `can(user_id, resource_type, resource_id, action)`")

    with FakeDB():
        async def scenario():
            results = {}
            # Egasi — hamma narsaga ruxsati bor.
            results["owner_publish"] = await R.can(OWNER_ID, "channel", CH_ID, "publish")
            results["owner_delete"] = await R.can(OWNER_ID, "channel", CH_ID, "delete_channel")
            # Muharrir — kontent, lekin rejalashtirish/publish yo'q.
            results["editor_create"] = await R.can(EDITOR_ID, "channel", CH_ID, "create")
            results["editor_edit"] = await R.can(EDITOR_ID, "channel", CH_ID, "edit")
            results["editor_approve"] = await R.can(EDITOR_ID, "channel", CH_ID, "approve")
            results["editor_publish"] = await R.can(EDITOR_ID, "channel", CH_ID, "publish")
            results["editor_schedule"] = await R.can(EDITOR_ID, "channel", CH_ID, "schedule")
            # Rejalashtiruvchi — faqat schedule/view.
            results["sched_schedule"] = await R.can(SCHEDULER_ID, "channel", CH_ID, "schedule")
            results["sched_approve"] = await R.can(SCHEDULER_ID, "channel", CH_ID, "approve")
            results["sched_publish"] = await R.can(SCHEDULER_ID, "channel", CH_ID, "publish")
            # Analitik — faqat o'qish + analitika.
            results["analyst_view"] = await R.can(ANALYST_ID, "channel", CH_ID, "view")
            results["analyst_analytics"] = await R.can(ANALYST_ID, "channel", CH_ID, "view_analytics")
            results["analyst_edit"] = await R.can(ANALYST_ID, "channel", CH_ID, "edit")
            # Begona foydalanuvchi (IDOR) — HECH NARSA.
            results["outsider_view"] = await R.can(OUTSIDER_ID, "channel", CH_ID, "view")
            results["outsider_publish"] = await R.can(OUTSIDER_ID, "channel", CH_ID, "publish")
            results["outsider_analytics"] = await R.can(OUTSIDER_ID, "channel", CH_ID, "view_analytics")
            # Noma'lum amal / resurs / user — fail-closed.
            results["unknown_action"] = await R.can(OWNER_ID, "channel", CH_ID, "hack_the_planet")
            results["unknown_resource"] = await R.can(OWNER_ID, "galaxy", "x", "view")
            results["invalid_user"] = await R.can(0, "channel", CH_ID, "view")
            results["missing_id"] = await R.can(OWNER_ID, "channel", "", "view")
            # Kalit-so'z shakli (topshiriqda ko'rsatilgan chaqiruv).
            results["kwargs_form"] = await R.can(
                user_id=OWNER_ID, resource_type="channel",
                resource_id=CH_ID, action="publish",
            )
            return results

        res = asyncio.run(scenario())

    expected_true = ["owner_publish", "owner_delete", "editor_create", "editor_edit",
                     "editor_approve", "sched_schedule", "analyst_view",
                     "analyst_analytics", "kwargs_form"]
    expected_false = ["editor_publish", "editor_schedule", "sched_approve",
                      "sched_publish", "analyst_edit", "outsider_view",
                      "outsider_publish", "outsider_analytics", "unknown_action",
                      "unknown_resource", "invalid_user", "missing_id"]
    for key in expected_true:
        check(f"ruxsat: {key}", res[key] is True, str(res[key]))
    for key in expected_false:
        check(f"rad: {key}", res[key] is False, str(res[key]))

    # Rad etishlar audit izi (WARNING log + xotira jurnali).
    denials = R.recent_denials(50)
    check("rad etishlar jurnalga yozildi", len(denials) >= 9, str(len(denials)))
    reasons = {d["reason"] for d in denials}
    check("sabablar aniq (not_a_channel_member/insufficient_role)",
          {"not_a_channel_member", "insufficient_role"} <= reasons, str(reasons))

    # Batafsil qaror (``check``) — rol va kanal ko'rsatiladi.
    with FakeDB():
        decision = asyncio.run(R.check(EDITOR_ID, "channel", CH_ID, "create"))
        denied = asyncio.run(R.check(OUTSIDER_ID, "channel", CH_ID, "create"))
    check("check(): ruxsat + rol", decision.allowed and decision.role == "editor",
          str(decision.as_dict()))
    check("check(): rad + sabab",
          not denied.allowed and denied.reason == "not_a_channel_member",
          str(denied.as_dict()))

    # DB umuman ishlamasa ham fail-closed.
    class BrokenDB:
        async def run_db(self, fn, *args, **kwargs):
            raise RuntimeError("db down")

    check("DB xatosi → ruxsat yo'q (fail-closed)",
          asyncio.run(R.can(OWNER_ID, "channel", CH_ID, "publish",
                            db_module=BrokenDB())) is False)


# ============================================================================
# 3) POST RESURSI
# ============================================================================
def test_post_resource():
    header("TEST 3: 🧩 Post resursi — post orqali kanalga IDOR tekshiruvi")
    with FakeDB():
        async def scenario():
            return {
                "owner_approve": await R.can(OWNER_ID, "post", POST_ID, "approve"),
                "editor_approve": await R.can(EDITOR_ID, "post", POST_ID, "approve"),
                "sched_approve": await R.can(SCHEDULER_ID, "post", POST_ID, "approve"),
                "outsider_approve": await R.can(OUTSIDER_ID, "post", POST_ID, "approve"),
                "editor_edit": await R.can(EDITOR_ID, "post", POST_ID, "edit"),
                "analyst_edit": await R.can(ANALYST_ID, "post", POST_ID, "edit"),
                # Begona post (boshqa kanalga tegishli) — begona foydalanuvchi uchun rad
                "forged_post": await R.can(OUTSIDER_ID, "post", 999999, "approve"),
            }
        res = asyncio.run(scenario())
    for key in ("owner_approve", "editor_approve", "editor_edit"):
        check(f"post ruxsati: {key}", res[key] is True, str(res[key]))
    for key in ("sched_approve", "outsider_approve", "analyst_edit", "forged_post"):
        check(f"post rad: {key}", res[key] is False, str(res[key]))


# ============================================================================
# 4) MIDDLEWARE QATLAMI
# ============================================================================
class _User:
    def __init__(self, uid):
        self.id = uid
        self.first_name = "Tester"
        self.is_bot = False


class _Msg:
    def __init__(self):
        self.chat_id = -100555
        self.message_id = 10
        self.sent = []
        self.edits = []
        self.from_user = _User(OWNER_ID)

    async def reply_text(self, text, **kwargs):
        self.sent.append(dict(text=text, **kwargs))
        return SimpleNamespace(message_id=11)


class _Query:
    def __init__(self, data, user_id=OWNER_ID):
        self.data = data
        self.from_user = _User(user_id)
        self.message = _Msg()
        self.answers = []
        self.edits = []

    async def answer(self, text=None, **kwargs):
        self.answers.append(dict(text=text, **kwargs))
        return True

    async def edit_message_text(self, text, **kwargs):
        self.edits.append(dict(text=text, **kwargs))
        return True

    async def edit_message_reply_markup(self, reply_markup=None):
        return True


def _update(query):
    return SimpleNamespace(
        callback_query=query, effective_user=query.from_user,
        effective_message=query.message, message=query.message,
    )


def _context(lang="uz", **user_data):
    data = {"lang": lang}
    data.update(user_data)
    return SimpleNamespace(user_data=data, chat_data={}, bot=SimpleNamespace())


def test_middleware_layer():
    header("TEST 4: 🛡 Middleware qatlami — validatsiya, alert, dekorator, PTB middleware")

    # --- payload validatsiyasi ---
    from middlewares import rbac as MW
    check("parse_resource_id: kanal ID", MW.parse_resource_id(CH_ID) == CH_ID)
    check("parse_resource_id: musbat son", MW.parse_resource_id("451") == "451")
    check("parse_resource_id: @username", MW.parse_resource_id("@kanalim") == "@kanalim")
    for bad in ("", "  ", "12;DROP", "1e5", "-", "<script>", "a" * 100):
        check(f"parse_resource_id rad: {bad!r}", MW.parse_resource_id(bad) is None)
    check("post ID qat'iy (musbat butun son)",
          MW.parse_resource_id("0", numeric=True) is None
          and MW.parse_resource_id("-5", numeric=True) is None
          and MW.parse_resource_id("451", numeric=True) == 451)

    upd = _update(_Query(f"team_ok:{POST_ID}"))
    check("post_id_from_callback: team_ok:501", MW.post_id_from_callback(upd, "team_ok:") == POST_ID)
    upd_bad = _update(_Query("team_ok:501;DROP"))
    check("post_id_from_callback: buzilgan payload → None",
          MW.post_id_from_callback(upd_bad, "team_ok:") is None)
    check("resource_id_from_callback: ch_np:<id>",
          MW.resource_id_from_callback(_update(_Query(f"ch_np:{CH_ID}")), "ch_np:") == CH_ID)
    check("resource_id_from_callback: set_style:<id>:<tone>",
          MW.resource_id_from_callback(_update(_Query(f"set_style:{CH_ID}:friendly")),
                                       "set_style:", index=0) == CH_ID)

    # --- enforce_resource_access: ruxsat / rad ---
    with FakeDB():
        ok_owner = asyncio.run(MW.enforce_resource_access(
            _update(_Query(f"ch_np:{CH_ID}")), resource_type="channel",
            resource_id=CH_ID, action="create"))
        q_denied = _Query(f"ch_np:{OTHER_CH_ID}", user_id=OUTSIDER_ID)
        ok_denied = asyncio.run(MW.enforce_resource_access(
            _update(q_denied), resource_type="channel",
            resource_id=OTHER_CH_ID, action="create"))
    check("enforce: egasi → True", ok_owner is True)
    check("enforce: begona → False (yopiq rad)", ok_denied is False)
    check("enforce: 'Permission Denied' alert ko'rsatildi",
          q_denied.answers and "Ruxsat yo'q" in (q_denied.answers[0]["text"] or "")
          and q_denied.answers[0].get("show_alert") is True,
          str(q_denied.answers))
    check("enforce: buzilgan resurs ID → rad (payload validatsiyasi)",
          asyncio.run(MW.enforce_resource_access(
              _update(_Query("ch_np:1;DROP")), resource_type="channel",
              resource_id="1;DROP", action="create", notify=False)) is False)
    check("enforce: so'rov egasi yo'q → rad",
          asyncio.run(MW.enforce_resource_access(
              _update(_Query(f"ch_np:{CH_ID}", user_id=0)), resource_type="channel",
              resource_id=CH_ID, action="create", notify=False)) is False)

    # --- require_resource_access: istisno ko'taradi ---
    from services.rbac_service import ResourcePermissionDenied
    with FakeDB():
        raised = False
        try:
            asyncio.run(MW.require_resource_access(
                _update(_Query(f"ch_np:{OTHER_CH_ID}", user_id=OUTSIDER_ID)),
                resource_type="channel", resource_id=OTHER_CH_ID,
                action="create", notify=False))
        except ResourcePermissionDenied as exc:
            raised = exc.decision.allowed is False
    check("require_resource_access: ResourcePermissionDenied ko'tarildi", raised)

    # --- resource_guard dekoratori ---
    calls = []

    @MW.resource_guard(resource_type="channel", action="create", prefix="ch_np:")
    async def _guarded(update, context):
        calls.append("executed")
        return "done"

    with FakeDB():
        allowed_q = _Query(f"ch_np:{CH_ID}")
        allowed_result = asyncio.run(_guarded(_update(allowed_q), _context()))
        denied_q = _Query(f"ch_np:{OTHER_CH_ID}", user_id=OUTSIDER_ID)
        denied_result = asyncio.run(_guarded(_update(denied_q), _context()))
    check("resource_guard: ruxsat bilan handler ishlaydi",
          allowed_result == "done" and calls == ["executed"], str(calls))
    check("resource_guard: ruxsat yo'q → handler UMUMAN chaqirilmaydi",
          denied_result is None and calls == ["executed"])

    # --- PTB middleware: ruxsatsiz callback zanjirdan chiqariladi ---
    from telegram import Update
    from telegram.ext import ApplicationHandlerStop

    def _real_update(data, user_id):
        return Update.de_json({
            "update_id": 1,
            "callback_query": {
                "id": "1", "from": {"id": user_id, "is_bot": False, "first_name": "T"},
                "chat_instance": "1", "data": data,
                "message": {"message_id": 5, "date": 0,
                            "chat": {"id": user_id, "type": "private"},
                            "text": "karta"},
            },
        }, None)

    with FakeDB():
        mw = MW.ResourceRBACMiddleware()
        matched = mw.check_update(_real_update(
            f"{MW.default_resource_rules()[0].prefix}{OTHER_CH_ID}", OUTSIDER_ID))
        check("middleware: begona kanal → qoida mos keladi",
              matched is not None and matched[1] == OTHER_CH_ID, str(matched))
        stopped = False
        try:
            asyncio.run(mw.handle_update(
                _real_update(f"ch_del:{OTHER_CH_ID}", OUTSIDER_ID),
                None, None, _context()))
        except ApplicationHandlerStop:
            stopped = True
        check("middleware: ruxsatsiz ch_del: → ApplicationHandlerStop", stopped)

        passed_through = True
        try:
            asyncio.run(mw.handle_update(
                _real_update(f"ch_del:{CH_ID}", OWNER_ID), None, None, _context()))
        except ApplicationHandlerStop:
            passed_through = False
        check("middleware: egasi uchun zanjir to'xtatilmaydi", passed_through)
        check("middleware: mos kelmaydigan update → None (aralashmaydi)",
              mw.check_update(_real_update("mnp_now", OWNER_ID)) is None)

    check("standart qoidalar: yozuvchi callback'lar qamrab olingan",
          {r.prefix for r in MW.default_resource_rules()} ==
          {"ch_del:", "ch_np:", "ch_ap:", "ch_voice:", "set_style:",
           "team_ok:", "team_no:", "team_edit:"})
    check("denied_message: 3 tilda mavjud",
          all(MW.denied_message(lang) for lang in ("uz", "ru", "en")))


# ============================================================================
# 5) MANUAL POST — IDOR
# ============================================================================
def test_manual_post_idor():
    header("TEST 5: ✍️ Manual post — begona kanalga YOZILMAYDI")
    import handlers.manual_post as MP

    def _ctx_manual(user_id=OWNER_ID):
        ctx = SimpleNamespace(
            user_data={MP.UD_CONTENT: "Tayyor post matni",
                       MP.UD_POST_TYPE: "text", MP.UD_MODE: MP.MODE_NOW,
                       "lang": "uz"},
            chat_data={}, bot=SimpleNamespace(), application=None,
        )
        return ctx

    # --- IDOR: begona kanal ---
    with FakeDB() as fake:
        msg = _Msg()
        state = asyncio.run(MP._publish(msg, _ctx_manual(OUTSIDER_ID), OUTSIDER_ID,
                                        OTHER_CH_ID, "Begona kanal", "uz"))
        written = fake.wrote("add_post")
        texts = " ".join(m["text"] for m in msg.sent)
    check("IDOR: post DB'ga YOZILMADI (add_post chaqirilmadi)",
          not written, str(written))
    check("IDOR: 'Permission Denied' xabari ko'rsatildi",
          "Ruxsat yo'q" in texts or "Permission denied" in texts, texts[:120])
    check("IDOR: oqim yakunlandi (END)",
          state == ConversationHandler.END, str(state))

    # --- IDOR: boshqa foydalanuvchi postni o'z kanalimga yozmoqchi ---
    with FakeDB() as fake:
        msg = _Msg()
        asyncio.run(MP._publish(msg, _ctx_manual(EDITOR_ID), EDITOR_ID,
                                OTHER_CH_ID, "Begona kanal", "uz"))
        check("IDOR: a'zo bo'lmagan foydalanuvchi ham yozolmaydi",
              not fake.wrote("add_post"), str(fake.writes))

    # --- REGRESSIYA: egasi odatdagidek yozadi ---
    with FakeDB() as fake:
        msg = _Msg()
        asyncio.run(MP._publish(msg, _ctx_manual(OWNER_ID), OWNER_ID,
                                CH_ID, "Eganing kanali", "uz"))
        written = fake.wrote("add_post")
    check("egasi: post baribir yoziladi (regressiya yo'q)",
          len(written) == 1, str(written))

    # --- MUHARRIR (channel_members) — kontent yaratish huquqi bor ---
    with FakeDB() as fake:
        msg = _Msg()
        asyncio.run(MP._publish(msg, _ctx_manual(EDITOR_ID), EDITOR_ID,
                                CH_ID, "Eganing kanali", "uz"))
        check("editor a'zosi: post yoziladi (create ruxsati)",
              len(fake.wrote("add_post")) == 1, str(fake.writes))

    # --- ANALITIK — faqat o'qish, yozish YO'Q ---
    with FakeDB() as fake:
        msg = _Msg()
        asyncio.run(MP._publish(msg, _ctx_manual(ANALYST_ID), ANALYST_ID,
                                CH_ID, "Eganing kanali", "uz"))
        check("analyst: post YOZILMAYDI (faqat analitika)",
              not fake.wrote("add_post"), str(fake.writes))


# ============================================================================
# 6) KANALLAR — IDOR (uzish / uslub / AI tahlil)
# ============================================================================
def test_channels_idor():
    header("TEST 6: 📢 Kanallar — uzish, uslub va AI tahlil IDOR tekshiruvi")
    import handlers.channels as CH

    # --- 🗑 ch_del: begona kanal ---
    with FakeDB() as fake:
        q = _Query(f"ch_del:{OTHER_CH_ID}", user_id=OUTSIDER_ID)
        asyncio.run(CH.remove_channel_callback(_update(q), _context()))
        removed = fake.wrote("remove_channel")
    check("ch_del: begona kanal uzilmadi (DB'ga yozuv yo'q)", not removed, str(removed))
    check("ch_del: 'Permission Denied' alert",
          any("Ruxsat yo'q" in (a.get("text") or "") for a in q.answers), str(q.answers))

    # --- 🗑 ch_del: egasi ishlaydi (regressiya) ---
    with FakeDB() as fake:
        q = _Query(f"ch_del:{CH_ID}", user_id=OWNER_ID)
        asyncio.run(CH.remove_channel_callback(_update(q), _context()))
        check("ch_del: egasi kanalni uza oladi (regressiya yo'q)",
              bool(fake.wrote("remove_channel")), str(fake.writes))

    # --- 🎨 set_style: begona kanal ---
    with FakeDB() as fake:
        q = _Query(f"set_style:{OTHER_CH_ID}:friendly", user_id=OUTSIDER_ID)
        asyncio.run(CH.tone_chosen_callback(_update(q), _context()))
        check("set_style: begona kanal uslubi o'zgartirilmadi",
              not fake.wrote("set_channel_tone"), str(fake.writes))
        check("set_style: foydalanuvchi xato xabarini oldi",
              bool(q.edits) or bool(q.message.sent), str(q.edits)[:80])

    # --- 🎨 set_style: egasi ishlaydi ---
    with FakeDB() as fake:
        q = _Query(f"set_style:{CH_ID}:formal", user_id=OWNER_ID)
        asyncio.run(CH.tone_chosen_callback(_update(q), _context()))
        check("set_style: egasi uslubni saqlay oladi (regressiya yo'q)",
              bool(fake.wrote("set_channel_tone")), str(fake.writes))

    # --- 🎙 ch_voice: begona kanal (AI tahlil kanal profiliga yozadi) ---
    with FakeDB() as fake:
        q = _Query(f"ch_voice:{OTHER_CH_ID}", user_id=OUTSIDER_ID)
        q.message.chat_id = 555
        asyncio.run(CH.channel_voice_analysis_callback(_update(q), _context()))
        check("ch_voice: begona kanal uchun tahlil boshlanmadi",
              not fake.calls_of("get_channel_posts_history"), str(fake.calls[-3:]))
        check("ch_voice: profil YOZILMADI",
              not fake.wrote("set_channel_tone"), str(fake.writes))

    # --- ➕ ch_np: begona kanal → post oqimi ochilmaydi ---
    with FakeDB() as fake:
        q = _Query(f"ch_np:{OTHER_CH_ID}", user_id=OUTSIDER_ID)
        state = asyncio.run(CH.channel_new_post_callback(_update(q), _context()))
        screen = ""
        if q.edits:
            screen = q.edits[-1].get("text") or ""
        check("ch_np: begona kanal uchun oqim ochilmadi",
              "topilmadi" in screen, screen[:80])
        check("ch_np: yangi post FSM'i ishga tushmadi",
              state == ConversationHandler.END and not fake.writes,
              f"{state} {fake.writes}")


# ============================================================================
# 7) AVTOPILOT — IDOR
# ============================================================================
def test_autopilot_idor():
    header("TEST 7: 🚀 Avtopilot — begona kanalda reja tuzilmaydi/rejalashtirilmaydi")
    import handlers.autopilot as AP

    # --- kirish (ch_ap:) begona kanal ---
    with FakeDB():
        q = _Query(f"ch_ap:{OTHER_CH_ID}", user_id=OUTSIDER_ID)
        state = asyncio.run(AP.channel_autopilot_entry(_update(q), _context()))
    check("ch_ap: begona kanal uchun holat o'zgarmadi (END)",
          state == ConversationHandler.END, str(state))
    check("ch_ap: 'Permission Denied' xabari",
          bool(q.edits) and "Ruxsat yo'q" in (q.edits[-1].get("text") or ""),
          str(q.edits)[:100])

    # --- kirish: egasi (regressiya) ---
    with FakeDB():
        q2 = _Query(f"ch_ap:{CH_ID}", user_id=OWNER_ID)
        state2 = asyncio.run(AP.channel_autopilot_entry(_update(q2), _context()))
    check("ch_ap: egasi uchun mavzu so'rovi (AUTOPILOT_TOPIC)",
          state2 == AP.AUTOPILOT_TOPIC, str(state2))

    # --- navbatga yozish: begona kanal (server-side user_data) ---
    scheduled = []

    async def _fake_schedule(user_id, channel_id, days):
        scheduled.append((user_id, channel_id))
        return {"success": True, "count": len(days)}

    original = AP.schedule_autopilot_week
    AP.schedule_autopilot_week = _fake_schedule
    try:
        with FakeDB():
            ctx = _context()
            ctx.user_data[AP.UD_CHANNEL] = OTHER_CH_ID
            ctx.user_data[AP.UD_TITLE] = "Begona kanal"
            q3 = _Query("ap_confirm", user_id=OUTSIDER_ID)
            AP.clear_autopilot_session(ctx)
            ctx.user_data[AP.UD_CHANNEL] = OTHER_CH_ID
            ctx.user_data[AP.UD_DAYS] = [{"post_text": "Post matni", "weekday": 0}]
            state3 = asyncio.run(AP._schedule_and_finish(
                q3, ctx, OUTSIDER_ID, [{"post_text": "Post matni", "weekday": 0}], "uz"))
            check("_schedule_and_finish: begona kanal → navbatga YOZILMADI",
                  not scheduled, str(scheduled))
            check("_schedule_and_finish: foydalanuvchi rad javobini oldi",
                  bool(q3.edits) and "Ruxsat yo'q" in (q3.edits[-1].get("text") or ""),
                  str(q3.edits)[:100])
            check("_schedule_and_finish: sessiya tozalandi (END)",
                  state3 == ConversationHandler.END, str(state3))

        with FakeDB():
            ctx2 = _context()
            ctx2.user_data[AP.UD_CHANNEL] = CH_ID
            ctx2.user_data[AP.UD_TITLE] = "Eganing kanali"
            days = [{"post_text": "Post matni", "weekday": 0}]
            q4 = _Query("ap_confirm", user_id=OWNER_ID)
            asyncio.run(AP._schedule_and_finish(q4, ctx2, OWNER_ID, days, "uz"))
            check("_schedule_and_finish: egasi uchun rejalashtirildi (regressiya)",
                  scheduled == [(OWNER_ID, CH_ID)], str(scheduled))
    finally:
        AP.schedule_autopilot_week = original


# ============================================================================
# 8) TEAM APPROVAL — IDOR
# ============================================================================
def test_team_approval_idor():
    header("TEST 8: 👥 Team approval — soxta payload bilan post o'g'irlanmaydi")
    import handlers.team as TM

    approved = []

    class _FakeTeamService:
        def __init__(self, _db):
            pass

        async def approve(self, post_id, user_id):
            approved.append(("approve", post_id, user_id))
            return {"ok": True}

        async def reject(self, post_id, user_id):
            approved.append(("reject", post_id, user_id))
            return {"ok": True}

    original = TM.TeamService
    TM.TeamService = _FakeTeamService
    try:
        # Begona post tasdiqlashga urinish (team_ok:<begona post>)
        with FakeDB():
            q = _Query(f"team_ok:{FOREIGN_POST_ID}", user_id=OUTSIDER_ID)
            asyncio.run(TM.team_approve_callback(_update(q), _context()))
        check("team_ok: begona post TASDIQLANMADI (servis chaqirilmadi)",
              not approved, str(approved))
        check("team_ok: 'Permission Denied' alert",
              any("Ruxsat yo'q" in (a.get("text") or "") for a in q.answers),
              str(q.answers))

        # Begona postni rad etishga urinish
        with FakeDB():
            q2 = _Query(f"team_no:{FOREIGN_POST_ID}", user_id=OUTSIDER_ID)
            asyncio.run(TM.team_reject_callback(_update(q2), _context()))
        check("team_no: begona post RAD ETILMADI", not approved, str(approved))

        # Tahrirlash oqimini o'g'irlash (ilgari tekshiruv YO'Q edi)
        with FakeDB():
            q3 = _Query(f"team_edit:{FOREIGN_POST_ID}", user_id=OUTSIDER_ID)
            ctx3 = _context()
            asyncio.run(TM.team_edit_callback(_update(q3), ctx3))
        check("team_edit: begona post tahrirlash oqimiga TUSHMADI",
              "team_edit_post_id" not in ctx3.user_data, str(ctx3.user_data))
        check("team_edit: 'Permission Denied' alert",
              any("Ruxsat yo'q" in (a.get("text") or "") for a in q3.answers),
              str(q3.answers))

        # Buzilgan payload — hech qanday servis chaqirilmaydi
        with FakeDB():
            q4 = _Query("team_ok:501;DROP", user_id=OWNER_ID)
            asyncio.run(TM.team_approve_callback(_update(q4), _context()))
        check("team_ok: buzilgan payload → rad", not approved, str(approved))

        # Egasi — ishlaydi (regressiya)
        with FakeDB():
            q5 = _Query(f"team_ok:{POST_ID}", user_id=OWNER_ID)
            asyncio.run(TM.team_approve_callback(_update(q5), _context()))
        check("team_ok: egasi postni tasdiqlay oladi (regressiya yo'q)",
              approved == [("approve", POST_ID, OWNER_ID)], str(approved))

        # Muharrir — approve ruxsati bor
        approved.clear()
        with FakeDB():
            q6 = _Query(f"team_ok:{POST_ID}", user_id=EDITOR_ID)
            asyncio.run(TM.team_approve_callback(_update(q6), _context()))
        check("team_ok: muharrir tasdiqlay oladi", approved == [("approve", POST_ID, EDITOR_ID)],
              str(approved))

        # Rejalashtiruvchi — approve ruxsati YO'Q
        approved.clear()
        with FakeDB():
            q7 = _Query(f"team_ok:{POST_ID}", user_id=SCHEDULER_ID)
            asyncio.run(TM.team_approve_callback(_update(q7), _context()))
        check("team_ok: scheduler tasdiqlay OLMAYDI (rol matritsasi)",
              not approved, str(approved))
    finally:
        TM.TeamService = original


# ============================================================================
# 9) NAVBAT — IDOR
# ============================================================================
def test_queue_idor():
    header("TEST 9: 🗑 Navbat — begona post o'chirilmaydi")
    import handlers.queue as Q

    with FakeDB() as fake:
        q = _Query(f"qdel:{FOREIGN_POST_ID}", user_id=OUTSIDER_ID)
        asyncio.run(Q.queue_delete_callback(_update(q), _context()))
        check("qdel: begona post uchun cancel_post CHAQIRILMADI",
              not fake.wrote("cancel_post"), str(fake.writes))
        check("qdel: foydalanuvchi 'topilmadi' xabarini oldi",
              bool(q.message.sent) or bool(q.edits), str(q.message.sent)[:80])

    with FakeDB() as fake:
        q2 = _Query(f"qdel:{POST_ID}", user_id=OWNER_ID)
        asyncio.run(Q.queue_delete_callback(_update(q2), _context()))
        check("qdel: egasi postni o'chira oladi (regressiya yo'q)",
              bool(fake.wrote("cancel_post")), str(fake.writes))


# ============================================================================
# 10) ADMIN CALLBACK QATLAMI (6-bosqich himoyasi buzilmagan)
# ============================================================================
def test_admin_layer_intact():
    header("TEST 10: 🔐 Admin callback qatlami (payload tampering) buzilmagan")
    check("CALLBACK_ID_MAX belgilangan", isinstance(R.CALLBACK_ID_MAX, int)
          and R.CALLBACK_ID_MAX > 0)
    for bad in ("", "-1", "1e3", "12;DROP", " 12", "+5", "0"):
        check(f"parse_callback_id rad: {bad!r}",
              R.parse_callback_id(bad) is None)
    check("parse_callback_id: '451' → 451", R.parse_callback_id("451") == 451)
    check("parse_callback_parts: ortiqcha bo'lak rad",
          R.parse_callback_parts("rc_ok:1:2", "rc_ok:", 1) is None)
    check("parse_callback_parts: to'g'ri payload",
          R.parse_callback_parts("rc_ok:451", "rc_ok:", 1) == [451])

    non_admin = _update(_Query("rc_ok:451", user_id=OUTSIDER_ID))
    admin = _update(_Query("rc_ok:451", user_id=ADMIN_USER_ID))
    check("verify_admin_callback: begona → False",
          R.verify_admin_callback(non_admin) is False)
    check("verify_admin_callback: ADMIN_ID → True",
          R.verify_admin_callback(admin) is True)
    tampering = False
    try:
        R.admin_callback_guard(non_admin, "rc_ok:", 1, R.PERM_MANAGE_PAYMENTS)
    except R.CallbackTampering:
        tampering = True
    check("admin_callback_guard: begona → CallbackTampering", tampering)


# ============================================================================
# 11) MAIN.PY INTEGRATSIYASI + REAL PTB GURUH ZANJIRI
# ============================================================================
def test_main_integration():
    header("TEST 11: 🔌 main.py integratsiyasi + real PTB guruh zanjiri")

    # --- (a) statik: main.py middleware'ni ro'yxatga oladimi? ---------------
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    check("main.py: install_resource_middleware import qilinadi",
          "from middlewares.rbac import install_resource_middleware" in src)
    call = re.search(
        r"install_resource_middleware\(\s*application\s*,\s*group=(-?\d+)\s*\)", src)
    check("main.py: install_resource_middleware(application, group=...) chaqiriladi",
          call is not None)
    check("main.py: middleware ALOHIDA guruhda (-2) — rate limiter (-1) buzilmagan",
          bool(call) and call.group(1) == "-2",
          call.group(1) if call else "chaqiruv topilmadi")
    check("main.py: middleware handler'lardan OLDIN ro'yxatga olinadi",
          src.find("install_resource_middleware(")
          < src.find("register_all_handlers(application)"))
    check("main.py: RateLimitMiddleware group=-1 (Phase 2 qulfi buzilmagan)",
          "add_handler(RateLimitMiddleware(), group=-1)" in src)
    from middlewares import install_resource_middleware as _install
    check("middlewares paketi install_resource_middleware'ni eksport qiladi",
          callable(_install))

    # --- (b) dinamik: haqiqiy PTB Application + guruh zanjiri (tarmoqsiz) ---
    with FakeDB() as fdb:
        from middlewares import rbac as MW
        from telegram.ext import ApplicationBuilder

        check("ResourceRBACMiddleware — PTB BaseHandler",
              issubclass(MW.ResourceRBACMiddleware, BaseHandler))

        class _Recorder(BaseHandler):
            """Guruh 0'dagi oddiy handler — chaqirilganini yozib boradi."""

            def __init__(self):
                super().__init__(callback=None, block=True)
                self.seen = []

            def check_update(self, update):
                return True

            async def handle_update(self, update, application, check_result, context):
                self.seen.append(getattr(update.callback_query, "data", None))
                return True

        async def scenario():
            app = ApplicationBuilder().token("123456:PHASE3_CHAIN").build()
            recorder = _Recorder()
            app.add_handler(recorder, group=0)
            mw = MW.install_resource_middleware(app, group=-2)
            check("install_resource_middleware: middleware nusxasi qaytariladi",
                  isinstance(mw, MW.ResourceRBACMiddleware))
            check("guruh tartibi: RBAC middleware eng birinchi (-2)",
                  list(app.handlers)[0] == -2, str(list(app.handlers)))

            context = SimpleNamespace(user_data={"lang": "uz"}, application=app)

            async def chain(update):
                """PTB ``process_update`` guruh mantiqini takrorlaydi."""
                stopped = False
                for group in list(app.handlers):
                    for handler in list(app.handlers[group]):
                        result = handler.check_update(update)
                        if result is None or result is False:
                            continue
                        try:
                            await handler.handle_update(update, app, result, context)
                        except ApplicationHandlerStop:
                            stopped = True
                        break
                    if stopped:
                        break
                return stopped

            # 1) Begona foydalanuvchi — middleware zanjirni to'xtatadi.
            outsider = _Query(f"ch_del:{CH_ID}", user_id=OUTSIDER_ID)
            stopped = await chain(_update(outsider))
            check("begona callback: middleware zanjirni TO'XTATDI", stopped is True)
            check("begona callback: handler UMUMAN ishga tushmadi", recorder.seen == [])
            check("begona callback: 'Permission Denied' alert ko'rsatildi",
                  any("Permission Denied" in str(a.get("text"))
                      for a in outsider.answers), str(outsider.answers))

            # 2) Kanal egasi — ruxsat bor, zanjir davom etadi.
            owner = _Query(f"ch_del:{CH_ID}", user_id=OWNER_ID)
            stopped = await chain(_update(owner))
            check("egasi callback: zanjir to'xtamadi", stopped is False)
            check("egasi callback: handler'ga YETIB BORDI",
                  recorder.seen == [f"ch_del:{CH_ID}"], str(recorder.seen))

        asyncio.run(scenario())
        check("main.py zanjiri: begona so'rov DB'ga yozmadi",
              fdb.wrote("remove_channel") == [], str(fdb.writes))


# ============================================================================
def main():
    print("=" * 70)
    print(" PHASE 3 — RBAC MARKAZLASHUVI + IDOR HIMOYASI TESTLARI")
    print("=" * 70)
    test_resource_roles()
    test_central_can()
    test_post_resource()
    test_middleware_layer()
    test_manual_post_idor()
    test_channels_idor()
    test_autopilot_idor()
    test_team_approval_idor()
    test_queue_idor()
    test_admin_layer_intact()
    test_main_integration()
    print("\n" + "=" * 70)
    print(f" JAMI: o'tdi={passed}, xato={failures}")
    print("=" * 70)
    if failures:
        print("PHASE 3 RBAC/IDOR TESTLARI: XATO ✘")
        return 1
    print("PHASE 3 RBAC/IDOR TESTLARI 100% YASHIL ✔")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover
        import traceback
        traceback.print_exc()
        print("FAIL:", exc)
        raise SystemExit(1)
