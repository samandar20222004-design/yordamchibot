#!/usr/bin/env python3
"""AUDIT-010: handlers/team.py foydalanuvchiga ko'rinadigan matnlari `locales.translations.get_text` (uz/ru/en) orqali.

Bu handler (barcha handlerlar kabi) `locales/` tizimidan foydalanadi (`get_text`); `translations/` tizimiga tegilmagan.
DB talab qilinmaydi.
"""
from __future__ import annotations

import ast
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456789:TESTMOCKTOKENabcdefghijklmnopqrstu")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "telegram_bot"))

import handlers.team as TM  # noqa: E402
from locales.translations import get_text  # noqa: E402

passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [XATO] {label} {detail}")


KEYS = ["team_err_post_id", "team_approved", "team_approve_denied", "team_rejected",
        "team_reject_failed", "team_edit_prompt", "team_approval_pending"]
print("== AUDIT-010: handlers/team.py i18n ==")

for key in KEYS:
    uz, ru, en = (get_text(key, lang) for lang in ("uz", "ru", "en"))
    check(f"{key}: uz/ru/en bor va bir-biridan farq qiladi",
          all(v and v != key for v in (uz, ru, en)) and len({uz, ru, en}) == 3, f"{uz!r} {ru!r} {en!r}")

# statik: handler ichida o'zbekcha foydalanuvchi matni (string literal) QOLMAGAN
tree = ast.parse((ROOT / "telegram_bot/handlers/team.py").read_text(encoding="utf-8"))
docstrings = {id(n.body[0].value) for n in ast.walk(tree)
              if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
              and n.body and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0], "value", None), ast.Constant)}
bad = [c.value for c in ast.walk(tree) if isinstance(c, ast.Constant) and isinstance(c.value, str) and id(c) not in docstrings
       and any(ch in c.value for ch in "❌✅⛔📝✏️")]
check("team.py da emoji'li qattiq yozilgan foydalanuvchi matni qolmadi", not bad, str(bad))


class Q:
    def __init__(self, data="team_ok:501", uid=7):
        self.data, self.from_user, self.answers, self.edits = data, SimpleNamespace(id=uid), [], []

    async def answer(self, text=None, **kw):
        self.answers.append(text)

    async def edit_message_text(self, text, **kw):
        self.edits.append(text)


class FakeTeam:
    ok = True

    def __init__(self, db):
        pass

    async def approve(self, pid, uid):
        return {"ok": FakeTeam.ok}

    async def reject(self, pid, uid):
        return {"ok": FakeTeam.ok}


async def allow(*a, **k):
    return True


def run(handler, query, lang, ok=True):
    FakeTeam.ok = ok
    ctx = SimpleNamespace(user_data={"lang": lang}, bot=None)
    saved = (TM.TeamService, TM.enforce_resource_access)
    TM.TeamService, TM.enforce_resource_access = FakeTeam, allow
    try:
        asyncio.run(handler(SimpleNamespace(callback_query=query), ctx))
    finally:
        TM.TeamService, TM.enforce_resource_access = saved
    return query.edits[-1] if query.edits else None


for lang in ("uz", "ru", "en"):
    check(f"[{lang}] tasdiqlash: muvaffaqiyat matni", run(TM.team_approve_callback, Q("team_ok:501"), lang, True) == get_text("team_approved", lang))
    check(f"[{lang}] tasdiqlash: ruxsat/holat xatosi matni", run(TM.team_approve_callback, Q("team_ok:501"), lang, False) == get_text("team_approve_denied", lang))
    check(f"[{lang}] rad etish: muvaffaqiyat", run(TM.team_reject_callback, Q("team_no:501"), lang, True) == get_text("team_rejected", lang))
    check(f"[{lang}] rad etish: xato", run(TM.team_reject_callback, Q("team_no:501"), lang, False) == get_text("team_reject_failed", lang))
    check(f"[{lang}] tahrirlash: ko'rsatma", run(TM.team_edit_callback, Q("team_edit:501"), lang) == get_text("team_edit_prompt", lang))
    check(f"[{lang}] buzilgan payload: xato matni", run(TM.team_approve_callback, Q("team_ok:501;DROP"), lang) == get_text("team_err_post_id", lang))


async def approval_request(lang, fail=False):
    sent = []

    async def send_message(**kw):
        sent.append(kw)
        return SimpleNamespace(message_id=1)

    async def fake_run_db(fn, *a, **k):
        if fail:
            raise RuntimeError("db down")
        return lang

    saved = TM.db.run_db
    TM.db.run_db = fake_run_db
    try:
        await TM.send_approval_request(SimpleNamespace(send_message=send_message), 55, 501, "Salom <b>x</b>")
    finally:
        TM.db.run_db = saved
    return sent[0]


for lang in ("uz", "ru", "en"):
    kw = asyncio.run(approval_request(lang))
    check(f"[{lang}] tasdiqlash kartasi sarlavhasi tilda", kw["text"].startswith(get_text("team_approval_pending", lang)), kw["text"][:50])
    check(f"[{lang}] karta: foydalanuvchi matni escape qilingan", "&lt;b&gt;x&lt;/b&gt;" in kw["text"])
kw = asyncio.run(approval_request("ru", fail=True))
check("til DB'dan olinmasa: uz zaxirasi, xabar baribir yuboriladi", kw["text"].startswith(get_text("team_approval_pending", "uz")))

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
