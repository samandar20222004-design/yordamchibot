#!/usr/bin/env python3
"""P3: ichki exception matni (SQL/DSN/parol bo'laklari bo'lishi mumkin) FOYDALANUVCHIGA chiqmasligi kerak.
Joylar: users_repository.transfer_user_credits, handlers/pending.cancel_post_callback, handlers/converter.
Statik qo'riqchi: handlers/*.py ichida get_text/safe_t'ga `error=<exception>` uzatilmasin. DB talab qilinmaydi."""
from __future__ import annotations

import ast
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456789:TESTMOCKTOKENabcdefghijklmnopqrstu")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

passed = failed = 0
SECRET = "postgresql://admin:SUPERSECRET@db.internal:5432/prod"


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [XATO] {label} {detail}")


print("== P3: exception matni foydalanuvchiga chiqmaydi ==")

# 1) repository
from contextlib import contextmanager  # noqa: E402

from repositories import users_repository as ur  # noqa: E402


@contextmanager
def boom(commit=False):
    raise RuntimeError(SECRET)
    yield  # pragma: no cover


with patch("database.db_cursor", boom):
    ok, msg = ur.transfer_user_credits(1, 2, 5)
check("transfer_user_credits: DB xatosida ok=False", ok is False)
check("transfer_user_credits: xabarda istisno matni (SECRET) YO'Q", "SUPERSECRET" not in msg and "postgresql" not in msg, msg)
check("transfer_user_credits: umumiy xabar (tarjima jadvalidagi kalit bilan bir xil)", msg == "Tizim xatoligi yuz berdi.", msg)

# 2) pending.cancel_post_callback
from handlers import pending as pend  # noqa: E402


async def cancel_flow():
    replies = []

    async def reply_text(text, **kw):
        replies.append(text)

    async def answer(*a, **k):
        return None

    query = SimpleNamespace(data="pend_cancel:5", from_user=SimpleNamespace(id=7), answer=answer,
                            message=SimpleNamespace(reply_text=reply_text))

    async def failing_run_db(fn, *a, **k):
        raise RuntimeError(SECRET)

    saved = pend.db.run_db
    pend.db.run_db = failing_run_db
    try:
        await pend.cancel_post_callback(SimpleNamespace(callback_query=query), SimpleNamespace(user_data={"lang": "uz"}))
    finally:
        pend.db.run_db = saved
    return replies


replies = asyncio.run(cancel_flow())
check("pending.cancel_post_callback: foydalanuvchiga xato xabari ketdi", len(replies) == 1, str(replies))
check("pending.cancel_post_callback: xabarda SECRET/DSN YO'Q", replies and "SUPERSECRET" not in replies[0] and "postgresql" not in replies[0], str(replies))

# 3) statik qo'riqchi: get_text/safe_t(..., error=<istisno>) yo'q
bad = []
for path in sorted((ROOT / "handlers").glob("*.py")):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in ("get_text", "safe_t", "t"):
            for kw in node.keywords:
                v = kw.value
                if kw.arg == "error" and (
                    (isinstance(v, ast.Name) and v.id in ("e", "exc", "ex"))
                    or (isinstance(v, ast.Call) and getattr(v.func, "id", "") == "str" and v.args
                        and isinstance(v.args[0], ast.Name) and v.args[0].id in ("e", "exc", "ex"))
                ):
                    bad.append(f"{path.name}:{node.lineno}")
check("handlers/*.py: get_text/safe_t'ga istisno obyekti/matni uzatilmaydi", not bad, str(bad))

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
