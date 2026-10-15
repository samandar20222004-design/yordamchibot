#!/usr/bin/env python3
"""Admin qo'lda PRO berganda kunlar YUQORI chegarasi (DB'siz).

Xato kiritish (masalan, 30 o'rniga 300000) muddatni buzmasligi kerak: `/grant_pro`, admin paneli va
`SubscriptionService.grant_admin_bonus` hammasi `MAX_ADMIN_GRANT_DAYS` dan oshganini DB'ga tegmasdan rad etadi.
Chegaraning o'zi (3650) ruxsat etiladi. Matn uch tilda.
"""
from __future__ import annotations

import asyncio
import os
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:GRANT_CAP_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [XATO] {label} {detail}")


import database as db  # noqa: E402
import handlers.admin as ADM  # noqa: E402
import handlers.subscription as SUB  # noqa: E402
from services import rbac_service  # noqa: E402
from services.rbac_service import AccessDecision  # noqa: E402
from services.subscription_service import MAX_ADMIN_GRANT_DAYS, SubscriptionService  # noqa: E402
from translations.admin_panel import admin_t  # noqa: E402

ADMIN = 777_000_111
SUB.ADMIN_IDS_SET = SUB.ADMIN_IDS_SET | {ADMIN}   # frozenset: test uchun nusxa
ADM.ADMIN_IDS_SET = ADM.ADMIN_IDS_SET | {ADMIN}

print("== Admin PRO berish: kunlar chegarasi ==")
check("chegara 3650 kun", MAX_ADMIN_GRANT_DAYS == 3650, str(MAX_ADMIN_GRANT_DAYS))

for lang in ("uz", "ru", "en"):
    t = admin_t("days_too_large", lang, max=MAX_ADMIN_GRANT_DAYS)
    check(f"[{lang}] days_too_large mavjud va chegarani ko'rsatadi", t != "days_too_large" and "3650" in t and "{max}" not in t, t)
check("uz/ru/en matnlari farq qiladi", len({admin_t("days_too_large", lg, max=1) for lg in ("uz", "ru", "en")}) == 3)

# --- SubscriptionService.grant_admin_bonus ---
calls = []
orig_activate = SubscriptionService.activate
SubscriptionService.activate = staticmethod(lambda *a, **k: calls.append((a, k)) or True)
try:
    check("chegaradan oshgan (3651) rad etiladi, activate chaqirilmaydi",
          SubscriptionService.grant_admin_bonus(1, MAX_ADMIN_GRANT_DAYS + 1, ADMIN) is False and calls == [])
    check("chegaraning o'zi (3650) ruxsat", SubscriptionService.grant_admin_bonus(1, MAX_ADMIN_GRANT_DAYS, ADMIN) is True and len(calls) == 1)
    check("0 / manfiy / int emas rad etiladi",
          all(SubscriptionService.grant_admin_bonus(1, d, ADMIN) is False for d in (0, -5, "30", 3.5)) and len(calls) == 1)
finally:
    SubscriptionService.activate = orig_activate


class Msg:
    def __init__(self, text=""):
        self.text = text
        self.sent = []

    async def reply_text(self, text, **kw):
        self.sent.append(text)


def run_with_fake_db(coro_factory):
    writes = []

    async def fake_run_db(fn, *args, **kw):
        if fn is db.set_user_plan:
            writes.append(args)
            return True
        if fn is db.get_user_language:
            return "uz"
        raise AssertionError(f"kutilmagan db chaqiruvi: {getattr(fn, '__name__', fn)}")

    async def fake_check(user_id, *, resource_type=None, resource_id=None, action=None, **kw):
        return AccessDecision(True, user_id=user_id, resource_id=str(resource_id), action=action, reason="ok")

    orig = (db.run_db, rbac_service.check, rbac_service.has_permission, ADM.has_permission, SUB.has_permission)
    db.run_db, rbac_service.check = fake_run_db, fake_check
    rbac_service.has_permission = ADM.has_permission = SUB.has_permission = lambda *a, **k: True   # soxta RBAC (@require_permission ham): DB'siz
    try:
        asyncio.run(coro_factory())
    finally:
        db.run_db, rbac_service.check, rbac_service.has_permission, ADM.has_permission, SUB.has_permission = orig
    return writes


def ctx(args=None, **ud):
    return SimpleNamespace(args=args or [], user_data={"lang": "ru", **ud}, bot=SimpleNamespace(send_message=_noop), chat_data={})


async def _noop(*a, **k):
    return None


# --- /grant_pro ---
def grant_cmd(days):
    msg = Msg()
    upd = SimpleNamespace(effective_user=SimpleNamespace(id=ADMIN), message=msg)
    writes = run_with_fake_db(lambda: SUB.grant_pro_command(upd, ctx([str(42), str(days)])))
    return writes, msg


writes, msg = grant_cmd(MAX_ADMIN_GRANT_DAYS + 1)
check("/grant_pro 3651: bazaga YOZILMAYDI", writes == [], str(writes))
check("/grant_pro 3651: admin tilida (ru) chegara haqida javob", len(msg.sent) == 1 and "3650" in msg.sent[0] and "Количество" in msg.sent[0], str(msg.sent))
writes, msg = grant_cmd(99_999_999_999)
check("/grant_pro juda katta son: yozilmaydi", writes == [], str(writes))
writes, msg = grant_cmd(MAX_ADMIN_GRANT_DAYS)
check("/grant_pro 3650: ruxsat, bazaga yoziladi", writes == [(42, "pro", MAX_ADMIN_GRANT_DAYS)], str(writes))
writes, msg = grant_cmd(30)
check("/grant_pro 30: oddiy xulq o'zgarmagan", writes == [(42, "pro", 30)], str(writes))


# --- Admin paneli oqimi ---
def panel(days):
    msg = Msg(f"42 {days}")
    upd = SimpleNamespace(effective_user=SimpleNamespace(id=ADMIN), message=msg, callback_query=None)
    c = ctx(admin_flow="grant_pro")
    writes = run_with_fake_db(lambda: ADM.admin_inline_text_handler(upd, c))
    return writes, msg


writes, msg = panel(MAX_ADMIN_GRANT_DAYS + 1)
check("admin paneli 3651: yozilmaydi va chegara haqida javob", writes == [] and msg.sent and "3650" in msg.sent[0], f"{writes} {msg.sent}")
writes, msg = panel(MAX_ADMIN_GRANT_DAYS)
check("admin paneli 3650: ruxsat", writes == [(42, "pro", MAX_ADMIN_GRANT_DAYS)], str(writes))

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
