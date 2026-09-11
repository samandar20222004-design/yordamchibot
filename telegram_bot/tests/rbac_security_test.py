#!/usr/bin/env python3
"""PostAssist V2 — 6-BOSQICH: RBAC, audit va xavfsizlik testlari.

Nima tekshiriladi
-----------------
1. **RBAC** — ``OWNER|SUPER_ADMIN|ADMIN|MODERATOR|FINANCE`` rollari va
   ``manage_payments / manage_promos / manage_users / system_settings``
   ruxsatlari topshiriqdagi matritsaga to'liq mos keladi; legacy
   ``ADMIN_ID``/``ADMIN_IDS`` ro'yxati avtomatik ``OWNER``/``SUPER_ADMIN``
   hisoblanadi; ``@require_permission`` / ``@require_role`` dekoratorlari
   ruxsatsiz adminni **handlerga kiritmaydi** va unga rad javobini yuboradi.
2. **Audit** — chek tasdiqlash/rad etish, PRO berish/bekor qilish va promo
   yaratish harakatlari ``admin_audit_logs`` jadvaliga TO'G'RI (admin, amal,
   obyekt, old/new JSONB) yoziladi; yozuv biznes tranzaksiyasi ichida
   bo'lgani uchun xatoda ROLLBACK bo'ladi (qismiy audit qolmaydi).
3. **Xavfsizlik** — ``safe_html()`` dinamik matnni escape qiladi (sindirilgan
   HTML teglar Telegram xatosini keltirib chiqarmaydi), ``validate_button_url()``
   esa faqat ``http://``, ``https://`` va ``tg://`` ga ruxsat beradi
   (``javascript:``, ``data:`` va h.k. rad etiladi).

Ishga tushirish
---------------
::

    cd telegram_bot && python tests/rbac_security_test.py

Haqiqiy PostgreSQL sinovi uchun ``pgserver`` kerak (``pip install pgserver``)
yoki ``RBAC_TEST_DATABASE_URL`` berilishi mumkin. Baza bo'lmasa statik
tekshiruvlar bajariladi, live qism o'tkazib yuboriladi.
"""
import os
import sys
import asyncio
import json
import random
import shutil
import tempfile
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("ADMIN_IDS", "123456789,555000111")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

failures = 0
passed = 0
skipped = 0


def check(name, cond, extra=""):
    global failures, passed
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


def skip(name, reason=""):
    global skipped
    skipped += 1
    print(f"  [SKIP] {name} {reason}")


# ============================================================
# 1. RBAC — RUXSAT MATRITSASI (DB talab qilinmaydi)
# ============================================================

def test_permission_matrix():
    """Topshiriqdagi ruxsatlar matritsasi aynan bajarilgan."""
    print("== RBAC: ruxsatlar matritsasi ==")
    from services.rbac_service import (
        Role, ROLE_PERMISSIONS, ALL_PERMISSIONS,
        PERM_MANAGE_PAYMENTS, PERM_MANAGE_PROMOS, PERM_MANAGE_USERS,
        PERM_SYSTEM_SETTINGS, permissions_for,
    )

    check("4 ta ruxsat e'lon qilingan", len(ALL_PERMISSIONS) == 4, str(ALL_PERMISSIONS))
    expected = {
        PERM_MANAGE_PAYMENTS: {Role.FINANCE, Role.SUPER_ADMIN, Role.OWNER},
        PERM_MANAGE_PROMOS: {Role.ADMIN, Role.SUPER_ADMIN, Role.OWNER},
        PERM_MANAGE_USERS: {Role.MODERATOR, Role.ADMIN, Role.SUPER_ADMIN, Role.OWNER},
        PERM_SYSTEM_SETTINGS: {Role.OWNER},
    }
    for perm, roles in expected.items():
        actual = {r for r, perms in ROLE_PERMISSIONS.items() if perm in perms}
        check(f"{perm}: {sorted(r.value for r in roles)}", actual == roles,
              f"topildi: {sorted(r.value for r in actual)}")

    check("FINANCE: to'lov bor, promo yo'q",
          PERM_MANAGE_PAYMENTS in permissions_for(Role.FINANCE)
          and PERM_MANAGE_PROMOS not in permissions_for(Role.FINANCE))
    check("MODERATOR: faqat foydalanuvchilar",
          permissions_for(Role.MODERATOR) == frozenset({PERM_MANAGE_USERS}))
    check("ADMIN: to'lov yo'q (faqat FINANCE/SUPER_ADMIN/OWNER)",
          PERM_MANAGE_PAYMENTS not in permissions_for(Role.ADMIN))
    check("USER: ruxsat yo'q", permissions_for(Role.USER) == frozenset())
    check("noma'lum rol → bo'sh to'plam", permissions_for("superhacker") == frozenset())
    check("parse_role: aliaslar", 
          __import__("services.rbac_service", fromlist=["parse_role"]).parse_role("superadmin")
          is Role.SUPER_ADMIN)


def test_legacy_admin_mapping():
    """Eski ADMIN_ID/ADMIN_IDS ro'yxati OWNER/SUPER_ADMIN ga aylanadi."""
    print("== RBAC: legacy ADMIN_IDS → OWNER/SUPER_ADMIN ==")
    from config import ADMIN_ID, ADMIN_IDS_SET
    from services.rbac_service import (
        Role, legacy_role, resolve_role, get_role, is_admin, is_legacy_admin,
        permissions_for, PERM_SYSTEM_SETTINGS,
    )

    check("ADMIN_ID → OWNER", legacy_role(int(ADMIN_ID)) is Role.OWNER, str(ADMIN_ID))
    check("boshqa ADMIN_IDS → SUPER_ADMIN",
          legacy_role(555000111) is Role.SUPER_ADMIN)
    check("begona user → None", legacy_role(999000777) is None)
    check("noto'g'ri qiymat → None", legacy_role("abc") is None and legacy_role(None) is None)

    check("OWNER hamma ruxsatlarga ega",
          permissions_for(Role.OWNER) == frozenset(
              ["manage_payments", "manage_promos", "manage_users", "system_settings"]))
    check("SUPER_ADMIN: tizim sozlamalari YO'Q",
          PERM_SYSTEM_SETTINGS not in permissions_for(Role.SUPER_ADMIN))

    # DB'dagi past rol legacy adminni pasaytirmaydi.
    check("legacy SUPER_ADMIN + DB 'finance' → SUPER_ADMIN",
          resolve_role(555000111, "finance") is Role.SUPER_ADMIN)
    check("legacy SUPER_ADMIN + DB 'owner' → OWNER",
          resolve_role(555000111, "owner") is Role.OWNER)
    check("oddiy user + DB 'finance' → FINANCE",
          resolve_role(999000777, "finance") is Role.FINANCE)
    check("oddiy user + rol yo'q → USER", resolve_role(999000777, None) is Role.USER)

    check("get_role(ADMIN_ID) DB'siz ham OWNER", get_role(int(ADMIN_ID)) is Role.OWNER)
    check("is_admin(ADMIN_ID)", is_admin(int(ADMIN_ID)) is True)
    check("is_admin(begona) False", is_admin(999000777) is False)
    check("is_legacy_admin", is_legacy_admin(555000111) and not is_legacy_admin(1))
    check("ADMIN_IDS_SET bo'sh emas", len(ADMIN_IDS_SET) >= 2, str(ADMIN_IDS_SET))


def test_role_coverage():
    """``require_role`` semantikasi: kuchli rol kuchsizini qamrab oladi."""
    print("== RBAC: rol qamrovi (require_role semantikasi) ==")
    from services.rbac_service import Role, role_covers, has_role

    check("SUPER_ADMIN ⊇ ADMIN", role_covers(Role.SUPER_ADMIN, Role.ADMIN))
    check("SUPER_ADMIN ⊇ MODERATOR", role_covers(Role.SUPER_ADMIN, Role.MODERATOR))
    check("ADMIN ⊇ MODERATOR", role_covers(Role.ADMIN, Role.MODERATOR))
    check("ADMIN ⊉ FINANCE (to'lov yo'q)", not role_covers(Role.ADMIN, Role.FINANCE))
    check("FINANCE ⊉ ADMIN (promo yo'q)", not role_covers(Role.FINANCE, Role.ADMIN))
    check("SUPER_ADMIN ⊇ FINANCE", role_covers(Role.SUPER_ADMIN, Role.FINANCE))
    check("OWNER ⊇ SUPER_ADMIN", role_covers(Role.OWNER, Role.SUPER_ADMIN))
    check("SUPER_ADMIN ⊉ OWNER", not role_covers(Role.SUPER_ADMIN, Role.OWNER))
    check("MODERATOR ⊉ ADMIN", not role_covers(Role.MODERATOR, Role.ADMIN))
    check("har qanday rol ⊇ USER", all(
        role_covers(r, Role.USER) for r in Role if r is not Role.USER))

    # has_role — legacy adminlar uchun DB'siz ishlaydi
    check("has_role(ADMIN_ID, OWNER)", has_role(123456789, Role.OWNER))
    check("has_role(ADMIN_ID, ADMIN)", has_role(123456789, Role.ADMIN))
    check("has_role(555000111, OWNER) False", not has_role(555000111, Role.OWNER))
    check("has_role(strict=True) faqat aynan rol",
          has_role(555000111, Role.SUPER_ADMIN, strict=True)
          and not has_role(555000111, Role.ADMIN, strict=True))


def test_has_permission_with_db_role():
    """DB'dagi rol ``has_permission`` ga to'g'ri ta'sir qiladi."""
    print("== RBAC: has_permission (DB roli simulyatsiyasi) ==")
    import services.rbac_service as rbac
    from services.rbac_service import (
        Role, has_permission, PERM_MANAGE_PAYMENTS, PERM_MANAGE_PROMOS,
        PERM_MANAGE_USERS, PERM_SYSTEM_SETTINGS,
    )

    matrix = {
        Role.OWNER:       (True, True, True, True),
        Role.SUPER_ADMIN: (True, True, True, False),
        Role.ADMIN:       (False, True, True, False),
        Role.MODERATOR:   (False, False, True, False),
        Role.FINANCE:     (True, False, False, False),
        Role.USER:        (False, False, False, False),
    }
    original = rbac.get_role
    try:
        for role, expected in matrix.items():
            rbac.get_role = lambda uid, r=role, **kw: r
            actual = (
                has_permission(424242, PERM_MANAGE_PAYMENTS),
                has_permission(424242, PERM_MANAGE_PROMOS),
                has_permission(424242, PERM_MANAGE_USERS),
                has_permission(424242, PERM_SYSTEM_SETTINGS),
            )
            check(f"{role.value}: payments/promos/users/settings {expected}",
                  actual == expected, f"topildi: {actual}")
    finally:
        rbac.get_role = original
    check("bo'sh ruxsat nomi → False", has_permission(123456789, "") is False)
    check("noto'g'ri ruxsat nomi → False",
          has_permission(123456789, "drop_database") is False)


# ============================================================
# 2. DEKORATORLAR — RUXSATSIZ ADMINGA RAD JAVOBI
# ============================================================

class _FakeUser:
    def __init__(self, uid):
        self.id = uid


class _FakeQuery:
    def __init__(self, uid, data="cb:x"):
        self.data = data
        self.from_user = _FakeUser(uid)
        self.answers = []

    async def answer(self, text=None, **kwargs):
        self.answers.append((text, kwargs))


class _FakeMessage:
    def __init__(self, uid):
        self.from_user = _FakeUser(uid)
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))


class _FakeCtx:
    """Minimal Context mock (``/audit 5`` kabi buyruqlar uchun)."""

    def __init__(self, args=None, bot=None):
        self.args = list(args or [])
        self.bot = bot
        self.user_data = {}


class _FakeUpdate:
    """Minimal Update mock (callback yoki xabar)."""

    def __init__(self, uid, as_callback=True, user=None):
        user = user or _FakeUser(uid)
        self.effective_user = user
        if as_callback:
            self.callback_query = _FakeQuery(uid)
            self.callback_query.from_user = user
            self.message = None
        else:
            self.callback_query = None
            self.message = _FakeMessage(uid)
            self.message.from_user = user


def test_require_permission_decorator():
    """Ruxsatli admin o'tadi, ruxsatsiz admin rad javobini oladi."""
    print("== RBAC: @require_permission dekoratori ==")
    import services.rbac_service as rbac
    from services.rbac_service import (
        Role, require_permission, require_role, PermissionDenied,
        PERM_MANAGE_PAYMENTS,
    )

    calls = {"ok": 0, "denied": 0}

    @require_permission(PERM_MANAGE_PAYMENTS)
    async def handler(update, context=None):
        calls["ok"] += 1
        return "bajarildi"

    @require_permission(PERM_MANAGE_PAYMENTS, raise_error=True)
    async def strict_handler(update, context=None):
        calls["denied"] += 1

    original = rbac.get_role
    try:
        # FINANCE — ruxsati bor
        rbac.get_role = lambda uid, **kw: Role.FINANCE
        result = asyncio.run(handler(_FakeUpdate(901)))
        check("ruxsatli admin handler ishladi", result == "bajarildi")
        check("ruxsatli admin rad javobisiz", calls == {"ok": 1, "denied": 0}, str(calls))

        # MODERATOR — ruxsati YO'Q (to'lov boshqaruvi yo'q)
        rbac.get_role = lambda uid, **kw: Role.MODERATOR
        upd = _FakeUpdate(902)
        result = asyncio.run(handler(upd))
        check("ruxsatsiz admin: handler chaqirilmadi", result is None and calls["ok"] == 1)
        check("ruxsatsiz admin: rad javobi (alert) yuborildi",
              upd.callback_query.answers
              and "ruxsat" in str(upd.callback_query.answers[0][0]).lower()
              and upd.callback_query.answers[0][1].get("show_alert") is True,
              str(upd.callback_query.answers))

        # Xabar orqali kelganda ham rad javobi
        upd_msg = _FakeUpdate(903, as_callback=False)
        rbac.get_role = lambda uid, **kw: Role.USER
        asyncio.run(handler(upd_msg))
        check("xabar orqali rad javobi", bool(upd_msg.message.replies)
              and "ruxsat" in upd_msg.message.replies[0][0].lower(),
              str(upd_msg.message.replies))

        # raise_error=True → PermissionDenied
        rbac.get_role = lambda uid, **kw: Role.MODERATOR
        raised = False
        try:
            asyncio.run(strict_handler(_FakeUpdate(904)))
        except PermissionDenied as e:
            raised = e.permission == PERM_MANAGE_PAYMENTS
        check("raise_error=True → PermissionDenied", raised)
        check("raise_error: handler chaqirilmadi", calls["denied"] == 0)

        # require_role: OWNER talabi FINANCE ni rad etadi, OWNER ni o'tkazadi
        @require_role(Role.OWNER, strict=True)
        async def owner_only(update, context=None):
            return "owner"

        rbac.get_role = lambda uid, **kw: Role.FINANCE
        check("require_role(OWNER, strict) FINANCE ni rad etadi",
              asyncio.run(owner_only(_FakeUpdate(905))) is None)
        rbac.get_role = lambda uid, **kw: Role.OWNER
        check("require_role(OWNER, strict) OWNER ni o'tkazadi",
              asyncio.run(owner_only(_FakeUpdate(906))) == "owner")
    finally:
        rbac.get_role = original

    # Legacy admin (ADMIN_ID) — DB'siz ham o'tadi
    upd = _FakeUpdate(123456789)
    check("legacy ADMIN_ID dekoratordan o'tadi",
          asyncio.run(handler(upd)) == "bajarildi" and not upd.callback_query.answers)

    check("dekorator metadatasi saqlanadi",
          getattr(handler, "__rbac_permission__", None) == PERM_MANAGE_PAYMENTS
          and callable(getattr(handler, "__rbac_original__", None)))


def test_decorator_used_in_handlers():
    """Haqiqiy handlerlar RBAC dekoratori bilan qo'riqlangan."""
    print("== RBAC: handlerlar dekorator bilan bog'langan ==")
    from handlers.subscription import grant_pro_command, create_promo_command
    from handlers import admin as admin_mod

    check("grant_pro_command: manage_users ruxsati",
          getattr(grant_pro_command, "__rbac_permission__", None) == "manage_users")
    check("create_promo_command: manage_promos ruxsati",
          getattr(create_promo_command, "__rbac_permission__", None) == "manage_promos")
    check("ai_settings_received: system_settings ruxsati",
          getattr(admin_mod.ai_settings_received, "__rbac_permission__", None)
          == "system_settings")
    check("post_tag_received: system_settings ruxsati",
          getattr(admin_mod.post_tag_received, "__rbac_permission__", None)
          == "system_settings")
    check("cache_clear_callback: system_settings ruxsati",
          getattr(admin_mod.cache_clear_callback, "__rbac_permission__", None)
          == "system_settings")

    # /audit buyrug'i — require_role bilan qo'riqlangan
    from services.rbac_service import Role
    from handlers.admin import admin_audit_command
    check("admin_audit_command: SUPER_ADMIN roli talab qilinadi",
          getattr(admin_audit_command, "__rbac_role__", None) == Role.SUPER_ADMIN,
          str(getattr(admin_audit_command, "__rbac_role__", None)))
    init_src = (ROOT / "handlers" / "__init__.py").read_text(encoding="utf-8")
    check("/audit ro'yxatdan o'tgan",
          'CommandHandler("audit", admin_audit_command)' in init_src)
    check("/audit fallback'dan oldin ro'yxatdan o'tgan",
          init_src.find('CommandHandler("audit"')
          < init_src.rfind("app.add_handler(MessageHandler(UNKNOWN_MESSAGE_FILTER"))

    # Fonksiyalar nomi saqlanadi (handler registratsiyasi buzilmaydi)
    check("wraps: __name__ saqlanadi",
          grant_pro_command.__name__ == "grant_pro_command"
          and create_promo_command.__name__ == "create_promo_command")

    # Manba: receipt callback 'manage_payments' ni tekshiradi
    receipt_src = (ROOT / "handlers" / "payment_receipt.py").read_text(encoding="utf-8")
    check("payment_receipt.py: manage_payments tekshiruvi",
          "PERM_MANAGE_PAYMENTS" in receipt_src
          and "has_permission(admin_id" in receipt_src)
    admin_src = (ROOT / "handlers" / "admin.py").read_text(encoding="utf-8")
    check("admin.py: adm_promo → manage_promos",
          "has_permission(query.from_user.id, PERM_MANAGE_PROMOS)" in admin_src)
    check("admin.py: adm_grant_pro → manage_users",
          "has_permission(query.from_user.id, PERM_MANAGE_USERS)" in admin_src)


# ============================================================
# 3. AUDIT SERVICE (statik qism)
# ============================================================

def test_audit_service_static():
    """AuditService API'si va yaroqsiz kiritmalarga chidamliligi."""
    print("== Audit: API va validatsiya ==")
    from services.audit_service import (
        AuditService, KNOWN_ACTIONS, ACTION_RECEIPT_APPROVE, ACTION_RECEIPT_REJECT,
        ACTION_GRANT_PRO, ACTION_REVOKE_PRO, ACTION_CREATE_PROMO,
    )

    check("amal nomlari aniqlangan", len(KNOWN_ACTIONS) >= 8, str(KNOWN_ACTIONS))
    check("chek tasdiqlash amali", ACTION_RECEIPT_APPROVE == "receipt_approve")
    check("chek rad etish amali", ACTION_RECEIPT_REJECT == "receipt_reject")
    check("PRO berish/olish amallari",
          ACTION_GRANT_PRO == "grant_pro" and ACTION_REVOKE_PRO == "revoke_pro")
    check("promo yaratish amali", ACTION_CREATE_PROMO == "create_promo")

    # Yaroqsiz admin/action — DB'siz ham xatosiz False (bot yiqilmaydi)
    check("admin_id=None → False", AuditService.log_action(None, "x") is False)
    check("admin_id=0 → False", AuditService.log_action(0, "x") is False)
    check("admin_id='salom' → False", AuditService.log_action("salom", "x") is False)
    check("bo'sh action → False", AuditService.log_action(1, "") is False)

    # JSONB'ga tushmaydigan qiymat ham xavfsiz (faqat DB yozuvi kerak emas —
    # shuning uchun mock kursor bilan tekshiramiz).
    from unittest.mock import patch
    from contextlib import contextmanager
    captured = {}

    class _Cur:
        def execute(self, sql, params=None):
            captured["sql"] = sql
            captured["params"] = params

        def fetchone(self):
            return None

    @contextmanager
    def _fake_dc(commit=False):
        yield _Cur()

    import database as db_mod
    with patch.object(db_mod, "db_cursor", _fake_dc):
        ok = AuditService.log_action(
            424242, "obscure_object_action" * 10,
            target_type="t" * 200, target_id="i" * 200,
            old_value={"set": {1, 2, 3}},  # to'g'ridan-to'g'ri JSON emas
            new_value=None, ip_or_metadata={"a": 1},
        )
    check("audit yozuvi mock kursor bilan OK", ok is True)
    check("action 64 belgiga qisqartirildi",
          captured["params"][1] and len(captured["params"][1]) <= 64, captured["params"][1])
    check("target_type 64 belgiga qisqartirildi",
          len(captured["params"][2]) <= 64)
    check("target_id 64 belgiga qisqartirildi", len(captured["params"][3]) <= 64)
    check("JSONB qiymatlar matn (::jsonb cast)", "::jsonb" in captured["sql"], captured["sql"])
    check("set → JSON massiv (serializatsiya xavfsiz)",
          json.loads(captured["params"][4]).get("set") == [1, 2, 3],
          captured["params"][4])


def test_owner_only_commands():
    """`/setrole`, `/delrole` — rollar boshqaruvi faqat OWNER uchun (strict)."""
    import services.rbac_service as rbac
    from services.rbac_service import Role
    from handlers.admin import admin_set_role_command, admin_del_role_command

    check("setrole: dekorator roli OWNER",
          getattr(admin_set_role_command, "__rbac_role__", None) is Role.OWNER,
          str(getattr(admin_set_role_command, "__rbac_role__", None)))
    check("delrole: dekorator roli OWNER",
          getattr(admin_del_role_command, "__rbac_role__", None) is Role.OWNER,
          str(getattr(admin_del_role_command, "__rbac_role__", None)))

    init_src = (ROOT / "handlers" / "__init__.py").read_text(encoding="utf-8")
    check("/setrole ro'yxatdan o'tgan",
          'CommandHandler("setrole", admin_set_role_command)' in init_src)
    check("/delrole ro'yxatdan o'tgan",
          'CommandHandler("delrole", admin_del_role_command)' in init_src)

    # SUPER_ADMIN ham o'tmaydi: dekorator strict=True bilan OWNER talab qiladi.
    original_get_role = rbac.get_role
    rbac.get_role = lambda uid, **kw: Role.SUPER_ADMIN
    try:
        update = _FakeUpdate(555000111, as_callback=False)
        asyncio.run(admin_set_role_command(update, _FakeCtx(args=["123456789", "admin"])))
        reply = update.message.replies[-1][0].lower() if update.message.replies else ""
        check("SUPER_ADMIN /setrole dan rad etiladi (faqat OWNER)",
              "faqat" in reply and "owner" in reply, reply)

        update_del = _FakeUpdate(555000111, as_callback=False)
        asyncio.run(admin_del_role_command(update_del, _FakeCtx(args=["123456789"])))
        reply_del = (update_del.message.replies[-1][0].lower()
                     if update_del.message.replies else "")
        check("SUPER_ADMIN /delrole dan rad etiladi (faqat OWNER)",
              "faqat" in reply_del and "owner" in reply_del, reply_del)
    finally:
        rbac.get_role = original_get_role


def test_audit_hooks_in_sources():
    """Audit chaqiruvlari biznes oqimlarining O'ZIDA (atomik) turibdi."""
    print("== Audit: servis oqimlaridagi hooklar ==")
    from tests.db_integrity_test import _function_body  # yordamchi skaner

    payment_src = (ROOT / "services" / "payment_service.py").read_text(encoding="utf-8")
    for fn, action in (("_approve_receipt", "log_receipt_decision"),
                       ("_reject_receipt", "log_receipt_decision")):
        body = _function_body(payment_src, fn)
        check(f"{fn}: audit chaqiruvi bor", action in body)
        check(f"{fn}: audit cur=cur (atomik)", "cur=cur" in body)
        check(f"{fn}: transaction() ichida",
              "with transaction() as cur:" in body)

    promo_src = (ROOT / "services" / "promo_service.py").read_text(encoding="utf-8")
    promo_body = _function_body(promo_src, "create_promo")
    check("create_promo: audit chaqiruvi", "log_promo_creation" in promo_body)
    check("create_promo: audit cur=cur", "cur=cur" in promo_body)
    check("create_promo: admin_id parametri", "admin_id" in promo_body)

    sub_src = (ROOT / "services" / "subscription_service.py").read_text(encoding="utf-8")
    for fn, action in (("activate", "log_pro_grant"), ("extend", "log_pro_grant"),
                       ("revoke", "log_pro_revoke")):
        body = _function_body(sub_src, fn)
        check(f"{fn}: audit {action}", action in body and "cur=cur" in body)

    db_src = (ROOT / "database.py").read_text(encoding="utf-8")
    check("database: log_admin_action mavjud", "def log_admin_action(" in db_src)
    check("database: admin_audit_logs INSERT", "INSERT INTO admin_audit_logs" in db_src)
    check("set_user_plan: admin_id uzatiladi", "admin_id=admin_id" in db_src)
    check("create_promo_code: admin_id uzatiladi",
          "plan_type, admin_id=admin_id" in db_src)


def test_schema_declares_rbac_audit():
    """schema.sql va database.py ro'yxatlari RBAC/audit obyektlarini e'lon qiladi."""
    print("== Schema: RBAC va audit jadvallari ==")
    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    import database as db_mod

    check("admin_roles jadvali", "CREATE TABLE IF NOT EXISTS admin_roles (" in schema)
    check("admin_audit_logs jadvali",
          "CREATE TABLE IF NOT EXISTS admin_audit_logs (" in schema)
    check("idx_audit_admin indeksi",
          "CREATE INDEX IF NOT EXISTS idx_audit_admin ON admin_audit_logs(admin_id, created_at);"
          in schema)
    for column in ("admin_id BIGINT NOT NULL", "action VARCHAR(64) NOT NULL",
                   "target_type VARCHAR(64)", "target_id VARCHAR(64)",
                   "old_value JSONB", "new_value JSONB", "ip_or_metadata JSONB",
                   "created_at TIMESTAMPTZ DEFAULT NOW()"):
        check(f"admin_audit_logs ustuni: {column[:28]}", column in schema)
    check("users.role ustuni (DEFAULT 'user')",
          "role VARCHAR(20) DEFAULT 'user'" in schema)
    check("users.role migratsiyasi (eski bazalar)",
          "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'user';" in schema)

    check("EXPECTED_TABLES: admin_roles", "admin_roles" in db_mod.EXPECTED_TABLES)
    check("EXPECTED_TABLES: admin_audit_logs",
          "admin_audit_logs" in db_mod.EXPECTED_TABLES)
    check("EXPECTED_INDEXES: idx_audit_admin", "idx_audit_admin" in db_mod.EXPECTED_INDEXES)
    check("_init_db_once: zaxira DDL bor",
          "CREATE TABLE IF NOT EXISTS admin_audit_logs" in
          (ROOT / "database.py").read_text(encoding="utf-8"))


# ============================================================
# 4. XAVFSIZLIK: HTML VA URL
# ============================================================

def test_safe_html():
    """``safe_html`` dinamik matnni escape qiladi (Telegram xatosi bo'lmaydi)."""
    print("== Xavfsizlik: safe_html ==")
    from utils.security import safe_html

    check("bo'sh → bo'sh", safe_html("") == "" and safe_html(None) == "")
    check("oddiy matn o'zgarmaydi", safe_html("Salom dunyo") == "Salom dunyo")

    escaped = safe_html("<b>Aziz</b>")
    check("foydalanuvchi ismi: <b> escape", escaped == "&lt;b&gt;Aziz&lt;/b&gt;", escaped)
    check("escape'da xom teg qolmadi", "<" not in escaped and ">" not in escaped)

    script = safe_html("<script>alert('xss')</script>")
    check("script tegi zararsizlantirildi",
          "<script>" not in script and "&lt;script&gt;" in script, script)

    broken = safe_html("<b>Yopilmagan <i>teg & <div>")
    check("sindirilgan HTML escape qilindi",
          "<" not in broken and "&lt;" in broken, broken)
    check("ampersand escape", safe_html("A & B") == "A &amp; B")
    check("qo'shtirnoq escape",
          safe_html('href="x"') == "href=&quot;x&quot;", safe_html('href="x"'))

    ai_leftover = safe_html("AI qoldi: <tg-spoiler>sir</tg-spoiler> & <code>x</code>")
    check("AI qoldiqlari escape (teg saqlanmaydi)",
          "<tg-spoiler>" not in ai_leftover and "&lt;tg-spoiler&gt;" in ai_leftover,
          ai_leftover)

    check("emoji saqlanadi", "👋" in safe_html("👋 Salom"))
    check("sonlar str() bo'ladi", safe_html(123) == "123")
    check("unicode ism buzilmaydi", safe_html("Аъзам Ҳакимов") == "Аъзам Ҳакимов")

    # Foydalanuvchi ismidan yasalgan xabar Telegram HTML uchun xavfsiz:
    template = f"👤 <b>{safe_html('<b>Fake Admin</b>')}</b> xabar yozdi"
    check("shablonda yagona <b> tegi qoldi",
          template.count("<b>") == 1 and template.count("</b>") == 1, template)
    check("escape qilingan ism ichida xom teg yo'q",
          "&lt;b&gt;Fake Admin&lt;/b&gt;" in template, template)

    # Yordamchi funksiyalar
    from utils.security import safe_text, normalize_username, strip_control_chars
    check("safe_text limiti", len(safe_text("<" * 50, max_len=10)) == 10)
    check("normalize_username @siz", normalize_username("@Aziz_2026") == "Aziz_2026")
    check("normalize_username bo'sh", normalize_username("") == ""
          and normalize_username(None) == "")
    check("normalize_username xavfli belgilar olib tashlanadi",
          normalize_username("a<script>") == "ascript")
    check("strip_control_chars", "\x00" not in strip_control_chars("a\x00b"))


def test_validate_button_url():
    """Faqat http/https/tg protokollari — qolgani rad etiladi."""
    print("== Xavfsizlik: validate_button_url ==")
    from utils.security import (
        validate_button_url, url_rejection_reason, ALLOWED_URL_SCHEMES,
        DANGEROUS_URL_SCHEMES,
    )

    check("oq ro'yxat: http, https, tg", ALLOWED_URL_SCHEMES == ("http", "https", "tg"))
    check("xavfli protokollar ro'yxati bor", "javascript" in DANGEROUS_URL_SCHEMES
          and "data" in DANGEROUS_URL_SCHEMES)

    safe_urls = (
        "https://t.me/kanal", "http://example.com/a?b=1",
        "tg://resolve?domain=yordamchibot", "https://t.me/x#anchor",
        "HTTPS://T.ME/KANAL", "https://example.com:8443/path",
    )
    for url in safe_urls:
        check(f"ruxsat: {url}", validate_button_url(url) is True, url_rejection_reason(url))

    dangerous = (
        "javascript:alert(1)", "JavaScript:alert(document.cookie)",
        "javascript://alert(1)", "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "vbscript:msgbox(1)", "file:///etc/passwd", "blob:https://x.com/abc",
        "about:blank", "jar:http://x.com/a.jar!/", "view-source:https://x.com",
        "t.me/kanal", "//evil.com", "", None, "   ",
    )
    for url in dangerous:
        check(f"RAD: {str(url)[:44]!r}", validate_button_url(url) is False,
              f"{url!r} → {url_rejection_reason(url)}")

    tricky = (
        "https://example.com/ http://evil.com",   # bo'sh joy
        "https://evil.com\njavascript:alert(1)",  # yangi qator
        "https://user:pass@evil.com/x",           # login/parol
        "https://",                                # domensiz
        "https://localhost",                       # domensiz
        "https://example.com:notaport/",           # buzuq port
        "<script>https://x.com</script>",          # HTML qoldig'i
        "https://x.com\\@evil.com",                # backslash hiylasi
    )
    for url in tricky:
        check(f"RAD (hiyla): {url[:38]!r}", validate_button_url(url) is False,
              f"{url!r} → {url_rejection_reason(url)}")

    # Sabab kodlari
    check("sabab: javascript → bad_scheme",
          url_rejection_reason("javascript:alert(1)") == "bad_scheme")
    check("sabab: data → bad_scheme",
          url_rejection_reason("data:text/html,x") == "bad_scheme")
    check("sabab: bo'sh → empty", url_rejection_reason("") == "empty")
    check("sabab: xavfsiz URL → ''", url_rejection_reason("https://t.me/x") == "")

    # utils.helpers bilan bir xil fikrda ishlaydi
    from utils.helpers import validate_button_url as helpers_validate
    for url in ("https://t.me/kanal", "javascript:alert(1)", "data:text/html,x",
                "https://user:pass@x.com"):
        ok_helpers, _err = helpers_validate(url)
        check(f"helpers ↔ security: {url[:32]}",
              ok_helpers is validate_button_url(url), url)


# ============================================================
# 5. REAL POSTGRESQL — RBAC + AUDIT END-TO-END
# ============================================================

def _start_test_postgres():
    """Test bazasi URI: RBAC_TEST_DATABASE_URL | INTEGRITY_TEST_DATABASE_URL | pgserver."""
    for var in ("RBAC_TEST_DATABASE_URL", "INTEGRITY_TEST_DATABASE_URL",
                "P0_TEST_DATABASE_URL"):
        url = os.getenv(var)
        if url and "user:pass" not in url:
            return url
    if os.getenv("RBAC_TEST_SKIP_LIVE") == "1":
        return None
    try:
        import pgserver
    except ImportError:
        return None
    server_dir = os.path.join(tempfile.gettempdir(), "yordamchi_pg_rbac")
    shutil.rmtree(server_dir, ignore_errors=True)
    try:
        return pgserver.get_server(server_dir).get_uri()
    except Exception as e:  # pragma: no cover - muhitga bog'liq
        print(f"  (pgserver ishga tushmadi: {e})")
        return None


def _seed_user(db_mod, user_id, plan="free", language="uz"):
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO users (user_id, username, full_name, plan_type, "
            "subscription_expires_at, language_code) "
            "VALUES (%s, %s, %s, %s, NULL, %s) "
            "ON CONFLICT (user_id) DO UPDATE SET plan_type = EXCLUDED.plan_type, "
            "subscription_expires_at = NULL, language_code = EXCLUDED.language_code",
            (user_id, f"rbac_test_{user_id}", "RBAC Test", plan, language),
        )


def _seed_receipt(db_mod, user_id, days=30):
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO payment_receipts (user_id, username, full_name, language_code, "
            "media_type, file_id, status, days_granted) "
            "VALUES (%s, %s, %s, 'uz', 'photo', %s, 'pending', %s) RETURNING id",
            (user_id, f"rbac_test_{user_id}", "RBAC Test", f"FILE_{user_id}", days),
        )
        return int(cur.fetchone()[0])


def _cleanup(db_mod, user_ids, admin_ids, codes):
    with db_mod.db_cursor(commit=True) as cur:
        for uid in user_ids:
            cur.execute("DELETE FROM payment_receipts WHERE user_id = %s", (uid,))
            cur.execute("DELETE FROM admin_roles WHERE user_id = %s", (uid,))
            cur.execute("DELETE FROM users WHERE user_id = %s", (uid,))
        for admin_id in admin_ids:
            cur.execute("DELETE FROM admin_audit_logs WHERE admin_id = %s", (admin_id,))
            cur.execute("DELETE FROM admin_roles WHERE user_id = %s", (admin_id,))
        for code in codes:
            cur.execute("DELETE FROM promo_codes WHERE code = %s", (code,))


def _live_rbac_audit_tests(db_mod):
    from services.rbac_service import (
        Role, get_role, has_permission, set_role, remove_role, list_admins,
        invalidate_role_cache, PERM_MANAGE_PAYMENTS, PERM_MANAGE_PROMOS,
        PERM_MANAGE_USERS, PERM_SYSTEM_SETTINGS,
    )
    from services.audit_service import (
        AuditService, ACTION_RECEIPT_APPROVE, ACTION_RECEIPT_REJECT,
        ACTION_GRANT_PRO, ACTION_REVOKE_PRO, ACTION_CREATE_PROMO,
    )
    from services.payment_service import PaymentService
    from services.subscription_service import SubscriptionService
    from services.promo_service import PromoService

    base = random.randint(10 ** 12, 9 * 10 ** 12)
    user_id, finance_id, admin_id, super_id = base + 1, base + 2, base + 3, base + 4
    codes = [f"RBAC{base % 10 ** 8}", f"RBACN{base % 10 ** 7}"]
    all_users = [user_id, finance_id, admin_id, super_id]
    admins = [finance_id, admin_id, super_id]

    _cleanup(db_mod, all_users, admins, codes)
    invalidate_role_cache()
    try:
        # --- 1) Jadvallar va ustunlar haqiqatan mavjud
        with db_mod.db_cursor() as cur:
            cur.execute("SELECT to_regclass('admin_audit_logs'), to_regclass('admin_roles')")
            audit_table, roles_table = cur.fetchone()
            cur.execute("SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'users' AND column_name = 'role'")
            role_column = cur.fetchone()
            cur.execute("SELECT indexname FROM pg_indexes WHERE indexname = 'idx_audit_admin'")
            audit_index = cur.fetchone()
        check("live: admin_audit_logs jadvali", audit_table is not None)
        check("live: admin_roles jadvali", roles_table is not None)
        check("live: users.role ustuni", role_column is not None)
        check("live: idx_audit_admin indeksi", audit_index is not None)

        # --- 2) Rollar: DB orqali berish/olish
        check("set_role: FINANCE berildi",
              set_role(finance_id, Role.FINANCE, granted_by=admin_id) is True)
        check("get_role: DB'dan FINANCE o'qildi", get_role(finance_id) is Role.FINANCE)
        check("FINANCE: manage_payments True",
              has_permission(finance_id, PERM_MANAGE_PAYMENTS) is True)
        check("FINANCE: manage_promos False",
              has_permission(finance_id, PERM_MANAGE_PROMOS) is False)
        check("FINANCE: manage_users False",
              has_permission(finance_id, PERM_MANAGE_USERS) is False)
        check("FINANCE: system_settings False",
              has_permission(finance_id, PERM_SYSTEM_SETTINGS) is False)

        _seed_user(db_mod, admin_id, plan="free")
        check("set_role: ADMIN berildi",
              set_role(admin_id, Role.ADMIN, granted_by=admin_id) is True)
        check("ADMIN: promo/users True, payments False",
              has_permission(admin_id, PERM_MANAGE_PROMOS)
              and has_permission(admin_id, PERM_MANAGE_USERS)
              and not has_permission(admin_id, PERM_MANAGE_PAYMENTS))

        check("set_role: MODERATOR (super_id)",
              set_role(super_id, Role.MODERATOR, granted_by=admin_id) is True)
        check("MODERATOR: payments/promos False, users True",
              not has_permission(super_id, PERM_MANAGE_PAYMENTS)
              and not has_permission(super_id, PERM_MANAGE_PROMOS)
              and has_permission(super_id, PERM_MANAGE_USERS))

        # users.role mirror
        with db_mod.db_cursor() as cur:
            cur.execute("SELECT role FROM users WHERE user_id = %s", (admin_id,))
            mirror_row = cur.fetchone()
        check("users.role mirror yangilandi",
              (mirror_row[0] if mirror_row else None) == "admin", str(mirror_row))

        # set_role → audit
        role_logs = AuditService.recent(limit=10, action="set_role")
        check("set_role auditi yozildi",
              any(l["target_id"] == str(finance_id) for l in role_logs), str(role_logs[:2]))
        check("set_role auditi: new_value JSONB",
              any((l["new_value"] or {}).get("role") == "finance" for l in role_logs))

        # Rolni olish
        check("remove_role", remove_role(admin_id, granted_by=finance_id) is True)
        check("rol o'chirildi → USER (legacy emas)", get_role(admin_id) is Role.USER)

        check("list_admins() ro'yxati", any(a["user_id"] == finance_id
                                            for a in list_admins()), str(list_admins()))

        # Legacy adminlar DB'siz/DB'dan qat'i nazar OWNER/SUPER_ADMIN
        check("legacy ADMIN_ID → OWNER (live)",
              get_role(123456789) is Role.OWNER)
        check("legacy ADMIN_IDS a'zosi → SUPER_ADMIN (live)",
              get_role(555000111) is Role.SUPER_ADMIN)
        check("legacy SUPER_ADMIN DB'dagi past rol bilan pasaymaydi",
              get_role(555000111) is Role.SUPER_ADMIN)

        # --- 3) Audit: chek tasdiqlash va rad etish
        _seed_user(db_mod, user_id, plan="free")
        receipt_ok = _seed_receipt(db_mod, user_id, days=30)
        before = AuditService.count(admin_id=finance_id, action=ACTION_RECEIPT_APPROVE)
        result = PaymentService.process_receipt(receipt_ok, finance_id, True)
        check("chek tasdiqlandi (ok)", result.get("ok") is True, str(result))
        logs = AuditService.recent(limit=5, admin_id=finance_id,
                                   action=ACTION_RECEIPT_APPROVE)
        check("chek tasdiqlash auditi yozildi",
              len(logs) == before + 1, str(logs[:1]))
        row = logs[0] if logs else {}
        check("audit: action=receipt_approve", row.get("action") == ACTION_RECEIPT_APPROVE)
        check("audit: admin_id to'g'ri", row.get("admin_id") == finance_id)
        check("audit: target_type=payment_receipt",
              row.get("target_type") == "payment_receipt")
        check("audit: target_id=chek ID", row.get("target_id") == str(receipt_ok))
        check("audit: old_value.status=pending",
              (row.get("old_value") or {}).get("status") == "pending", str(row.get("old_value")))
        check("audit: new_value.status=approved",
              (row.get("new_value") or {}).get("status") == "approved", str(row.get("new_value")))
        check("audit: new_value.days_granted=30",
              (row.get("new_value") or {}).get("days_granted") == 30)
        check("audit: ip_or_metadata JSONB (logged_at)",
              isinstance(row.get("ip_or_metadata"), dict)
              and "logged_at" in row["ip_or_metadata"], str(row.get("ip_or_metadata")))

        # Takroriy tasdiqlash — yangi audit yozuvi QO'SHILMAYDI (atomik shart)
        count_before = AuditService.count(action=ACTION_RECEIPT_APPROVE)
        again = PaymentService.process_receipt(receipt_ok, finance_id, True)
        check("takroriy tasdiqlash rad etildi", again.get("ok") is False, str(again))
        check("takroriy tasdiqlashda audit ko'paymadi",
              AuditService.count(action=ACTION_RECEIPT_APPROVE) == count_before)

        receipt_no = _seed_receipt(db_mod, user_id, days=30)
        rejected = PaymentService.process_receipt(receipt_no, finance_id, False)
        check("chek rad etildi (ok)", rejected.get("ok") is True, str(rejected))
        rej_logs = AuditService.recent(limit=3, action=ACTION_RECEIPT_REJECT)
        check("rad etish auditi yozildi",
              any(l["target_id"] == str(receipt_no) for l in rej_logs), str(rej_logs[:1]))
        with db_mod.db_cursor() as cur:
            cur.execute("SELECT status FROM payment_receipts WHERE id = %s", (receipt_no,))
            status = cur.fetchone()[0]
        check("DB: chek statusi 'rejected'", status == "rejected", status)

        # --- 4) Atomiklik: tranzaksiya xatosi audit yozuvini ham qaytaradi
        receipt_boom = _seed_receipt(db_mod, user_id, days=30)
        audit_before = AuditService.count(action=ACTION_RECEIPT_APPROVE)

        class _Boom:
            def __init__(self, cur, marker):
                self._cur = cur
                self._marker = marker

            def execute(self, sql, params=None):
                if self._marker in str(sql):
                    raise RuntimeError("rbac probe: injected failure")
                return self._cur.execute(sql, params)

            def fetchone(self):
                return self._cur.fetchone()

            def fetchall(self):
                return self._cur.fetchall()

            @property
            def rowcount(self):
                return self._cur.rowcount

            def close(self):
                pass

        from contextlib import contextmanager
        from unittest.mock import patch
        real_dc = db_mod.db_cursor

        @contextmanager
        def _explosive(commit=False):
            with real_dc(commit=commit) as cur:
                yield _Boom(cur, "UPDATE payment_receipts SET status = 'approved'")

        with patch("services.payment_service.db_cursor", _explosive):
            failed = PaymentService.process_receipt(receipt_boom, finance_id, True)
        check("xato yutiladi (ok=False)", failed.get("ok") is False, str(failed))
        check("xatoda audit yozuvi ham YOZILMADI",
              AuditService.count(action=ACTION_RECEIPT_APPROVE) == audit_before)
        with db_mod.db_cursor() as cur:
            cur.execute("SELECT status FROM payment_receipts WHERE id = %s", (receipt_boom,))
            status = cur.fetchone()[0]
        check("xatoda chek 'pending' holatida qoldi (ROLLBACK)", status == "pending", status)

        # --- 5) PRO berish / bekor qilish auditi
        _seed_user(db_mod, user_id, plan="free")
        granted = SubscriptionService.activate(user_id, "pro", 45, admin_id=admin_id)
        check("PRO berildi", granted is True)
        grant_logs = AuditService.recent(limit=3, admin_id=admin_id, action=ACTION_GRANT_PRO)
        check("PRO berish auditi yozildi", bool(grant_logs), str(grant_logs[:1]))
        check("audit: grant_pro target=user",
              grant_logs and grant_logs[0]["target_type"] == "user"
              and grant_logs[0]["target_id"] == str(user_id))
        check("audit: grant_pro new_value.days=45",
              grant_logs and (grant_logs[0]["new_value"] or {}).get("days") == 45)
        with db_mod.db_cursor() as cur:
            cur.execute("SELECT plan_type, subscription_expires_at FROM users WHERE user_id = %s",
                        (user_id,))
            plan, expires = cur.fetchone()
        check("DB: foydalanuvchi PRO bo'ldi", plan == "pro" and expires is not None,
              f"{plan}/{expires}")

        revoked = SubscriptionService.revoke(user_id, admin_id=admin_id, old_plan="pro")
        check("PRO bekor qilindi", revoked is True)
        revoke_logs = AuditService.recent(limit=3, action=ACTION_REVOKE_PRO)
        check("PRO bekor qilish auditi yozildi",
              any(l["target_id"] == str(user_id) for l in revoke_logs), str(revoke_logs[:1]))

        # admin bo'lmagan (admin_id=None) oqim audit yozmaydi
        before_grant = AuditService.count(action=ACTION_GRANT_PRO)
        SubscriptionService.activate(user_id, "pro", 10)
        check("admin_id=None → audit yozilmaydi",
              AuditService.count(action=ACTION_GRANT_PRO) == before_grant)

        # --- 6) Promo-kod yaratish auditi
        check("promo-kod yaratildi",
              PromoService.create_promo(codes[0], 30, 5, admin_id=super_id) is True)
        promo_logs = AuditService.recent(limit=3, admin_id=super_id,
                                         action=ACTION_CREATE_PROMO)
        check("promo auditi yozildi", bool(promo_logs), str(promo_logs[:1]))
        check("audit: promo target_id=code",
              promo_logs and promo_logs[0]["target_type"] == "promo_code"
              and promo_logs[0]["target_id"] == codes[0])
        check("audit: promo new_value days=30",
              promo_logs and (promo_logs[0]["new_value"] or {}).get("duration_days") == 30)

        # Takroriy (CONFLICT) yaratish audit yozmaydi
        promo_before = AuditService.count(action=ACTION_CREATE_PROMO)
        dup = PromoService.create_promo(codes[0], 30, 5, admin_id=super_id)
        check("dublikat promo yaratilmadi", dup is False)
        check("dublikatda audit ko'paymadi",
              AuditService.count(action=ACTION_CREATE_PROMO) == promo_before)

        # --- 7) Dekorator + real DB roli: ruxsatsiz admin rad etiladi
        from services.rbac_service import require_permission
        calls = {"n": 0}

        @require_permission(PERM_MANAGE_PROMOS)
        async def promo_handler(update, context=None):
            calls["n"] += 1
            return "ok"

        fin_update = _FakeUpdate(finance_id)
        result = asyncio.run(promo_handler(fin_update))
        check("FINANCE promo handleridan o'ta olmaydi",
              result is None and calls["n"] == 0)
        check("FINANCE rad javobini oldi",
              bool(fin_update.callback_query.answers)
              and "ruxsat" in str(fin_update.callback_query.answers[0][0]).lower())

        promo_update = _FakeUpdate(super_id, as_callback=False)
        # super_id hozir MODERATOR — promo ham rad etiladi
        check("MODERATOR promo handleridan o'ta olmaydi",
              asyncio.run(promo_handler(promo_update)) is None and calls["n"] == 0)

        set_role(super_id, Role.ADMIN, granted_by=finance_id)
        check("ADMIN berilgach promo handler ishlaydi",
              asyncio.run(promo_handler(_FakeUpdate(super_id))) == "ok" and calls["n"] == 1)

        # --- 8) /audit buyrug'i: OWNER ko'radi, boshqalar rad javobini oladi
        from handlers.admin import admin_audit_command
        owner_update = _FakeUpdate(123456789, as_callback=False)
        asyncio.run(admin_audit_command(owner_update, _FakeCtx(args=["5"])))
        check("OWNER /audit jurnalini ko'radi",
              bool(owner_update.message.replies)
              and "admin harakatlari" in owner_update.message.replies[-1][0].lower(),
              str(owner_update.message.replies[:1]))

        denied_update = _FakeUpdate(finance_id, as_callback=False)
        if get_role(finance_id) is Role.FINANCE:
            asyncio.run(admin_audit_command(denied_update, _FakeCtx(args=["5"])))
            reply_text = (denied_update.message.replies[-1][0].lower()
                          if denied_update.message.replies else "")
            check("FINANCE /audit dan rad javobini oladi",
                  "faqat" in reply_text and "owner" in reply_text, reply_text)

        # --- 8b) /setrole va /delrole (OWNER) — rol DB'ga yoziladi va audit
        from handlers.admin import admin_set_role_command, admin_del_role_command
        new_admin = base + 5
        all_users.append(new_admin)
        _seed_user(db_mod, new_admin, plan="free")
        role_update = _FakeUpdate(123456789, as_callback=False)
        asyncio.run(admin_set_role_command(
            role_update, _FakeCtx(args=[str(new_admin), "finance"])))
        check("OWNER /setrole orqali rol beradi",
              bool(role_update.message.replies)
              and "rol berildi" in role_update.message.replies[-1][0].lower(),
              str(role_update.message.replies[:1]))
        invalidate_role_cache()
        check("yangi rol DB'dan FINANCE o'qildi", get_role(new_admin) is Role.FINANCE)
        with db_mod.db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM admin_audit_logs "
                        "WHERE admin_id = %s AND action = 'set_role' "
                        "AND target_id = %s", (123456789, str(new_admin)))
            set_role_rows = cur.fetchone()[0]
        check("set_role auditi yozildi", set_role_rows >= 1, str(set_role_rows))

        del_update = _FakeUpdate(123456789, as_callback=False)
        asyncio.run(admin_del_role_command(del_update, _FakeCtx(args=[str(new_admin)])))
        check("OWNER /delrole orqali rolni oladi",
              bool(del_update.message.replies)
              and "olib tashlandi" in del_update.message.replies[-1][0].lower(),
              str(del_update.message.replies[:1]))
        invalidate_role_cache()
        check("rol olib tashlandi (USER)", get_role(new_admin) is Role.USER)
        with db_mod.db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM admin_audit_logs "
                        "WHERE admin_id = %s AND action = 'remove_role' "
                        "AND target_id = %s", (123456789, str(new_admin)))
            remove_rows = cur.fetchone()[0]
        check("remove_role auditi yozildi", remove_rows >= 1, str(remove_rows))

        # --- 9) Audit jadvali indeksdan foydalanadi (sxema tekshiruvi)
        with db_mod.db_cursor() as cur:
            cur.execute("SELECT indexdef FROM pg_indexes WHERE indexname = 'idx_audit_admin'")
            idx = cur.fetchone()
        check("idx_audit_admin (admin_id, created_at)",
              idx and "admin_id" in idx[0] and "created_at" in idx[0], str(idx))
    finally:
        _cleanup(db_mod, all_users, admins, codes)
        invalidate_role_cache()


# ============================================================
# MAIN
# ============================================================

def main():
    # Statik testlarda baza yo'q (dummy DATABASE_URL) — RBAC DB o'qishini
    # "rol yo'q" deb taqlid qilamiz, shunda ortiqcha ulanish urinishlari
    # (va log shovqini) bo'lmaydi. Live bo'limda asl funksiya qaytariladi.
    import database as db_mod
    from services.rbac_service import invalidate_role_cache
    original_get_admin_role = db_mod.get_admin_role
    db_mod.get_admin_role = lambda user_id: None
    invalidate_role_cache()
    try:
        test_permission_matrix()
        test_legacy_admin_mapping()
        test_role_coverage()
        test_has_permission_with_db_role()
        test_require_permission_decorator()
        test_decorator_used_in_handlers()
        test_owner_only_commands()
        test_audit_service_static()
        test_audit_hooks_in_sources()
        test_schema_declares_rbac_audit()
        test_safe_html()
        test_validate_button_url()
    finally:
        db_mod.get_admin_role = original_get_admin_role
        invalidate_role_cache()

    uri = _start_test_postgres()
    if not uri:
        print("\n== Real PostgreSQL (o'tkazib yuborildi) ==")
        skip("live RBAC/audit testlari", "(pgserver/RBAC_TEST_DATABASE_URL mavjud emas)")
    else:
        import database as db_mod
        db_mod.DATABASE_URL = uri
        os.environ["DATABASE_URL"] = uri
        db_mod._reset_pool()
        try:
            db_mod.init_db()
            _live_rbac_audit_tests(db_mod)
        except Exception as e:
            check("live RBAC/audit testlari xatosiz o'tdi", False,
                  f"{type(e).__name__}: {e}")
        finally:
            db_mod.close_pool()

    print()
    if failures:
        print(f"O'tdi: {passed}, Xato: {failures}, O'tkazib yuborildi: {skipped}")
        print("RBAC/xavfsizlik testlarida xatolar bor ✗")
        sys.exit(1)
    print(f"O'tdi: {passed}, Xato: 0, O'tkazib yuborildi: {skipped}")
    print("Barcha RBAC va xavfsizlik testlari muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
