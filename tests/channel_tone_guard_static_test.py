#!/usr/bin/env python3
"""AUDIT-012: `set_channel_tone(channel_id, tone)` egasiz UPDATE qiladi (WHERE channel_id AND is_active).

Repository'ga `user_id` sharti QO'SHILMAGAN: kanal uslubini egasi, `channel_members` orqali editor roli va admin
o'zgartira oladi (markaziy RBAC `_rbac_channel_allowed`/`enforce_resource_access`), shu sababli chaqiruvchining
`user_id`si bo'yicha filtr qonuniy jamoa/admin oqimlarini buzardi. Himoya handler qatlamida; bu test uni QULFLAYDI:
`set_channel_tone` ni chaqiradigan HAR BIR funksiya o'sha funksiya ichida RBAC tekshiruvini ham chaqirishi shart
(yangi chaqiruvchi tekshiruvni unutsa test yiqiladi).
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
GUARDS = {"_rbac_channel_allowed", "enforce_resource_access", "_owned_channel"}
passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [XATO] {label} {detail}")


def called_names(node):
    names = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            names.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
    return names


def mentions(node, name):
    return any((isinstance(n, ast.Attribute) and n.attr == name) or (isinstance(n, ast.Name) and n.id == name)
               for n in ast.walk(node))


print("== AUDIT-012: set_channel_tone chaqiruvchilari RBAC bilan himoyalangan ==")
sites = 0
for path in sorted(ROOT.rglob("*.py")):
    if "tests" in path.parts or "__pycache__" in path.parts:
        continue
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.name == "set_channel_tone":
            continue
        # funksiya tanasida set_channel_tone'ga murojaat (db.run_db(db.set_channel_tone, ...) yoki to'g'ridan chaqiruv)
        uses = [n for n in ast.walk(fn) if (isinstance(n, ast.Attribute) and n.attr == "set_channel_tone")]
        # ichki funksiyalar alohida hisoblanadi: faqat shu funksiyaning o'z tanasi
        if not uses or any(n is not fn and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                           and any(u in ast.walk(n) for u in uses) for n in ast.walk(fn)):
            continue
        rel = path.relative_to(ROOT)
        if str(rel) == "database.py":
            continue  # facade re-export (from repositories ... import set_channel_tone) — chaqiruv emas
        sites += 1
        guarded = bool(called_names(fn) & GUARDS)
        check(f"{rel}:{fn.name} — set_channel_tone'dan oldin RBAC/egalik tekshiruvi bor", guarded, str(called_names(fn) & GUARDS))
check("kamida bitta chaqiruvchi topildi (test o'zi bo'sh emas)", sites >= 3, f"topildi={sites}")

# repository: noto'g'ri uslub qiymati DB'ga yetmasdan rad etiladi
sys.path.insert(0, str(ROOT))
import os  # noqa: E402

os.environ.setdefault("BOT_TOKEN", "123456789:TESTMOCKTOKENabcdefghijklmnopqrstu")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
from repositories.channels_repository import set_channel_tone  # noqa: E402

check("noto'g'ri uslub: False (DB'ga murojaatsiz)", set_channel_tone("-100123", "<script>") is False)

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
