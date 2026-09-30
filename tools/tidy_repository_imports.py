# -*- coding: utf-8 -*-
"""Bir martalik tozalash: repository modullaridagi takror import qatorlari.

Avvalgi generator ``import hashlib`` / ``from datetime import ...`` kabi
qatorlarni STDLIB bloki va o'tkazilgan asl import bir vaqtda yozib
yuborgan. Bu skript faqat shu takrorlarni olib tashlaydi — kod
mantiqiga tegmaydi, import qatorlarini toza qiladi.

Idempotent: ikkinchi marta ishga tushsa hech narsa o'zgarmaydi.
"""
import ast
import os
import sys

REPOS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "telegram_bot", "repositories")


def bound_names(stmt):
    """Import qatori bog'laydigan nomlar."""
    if isinstance(stmt, ast.Import):
        return [a.asname or a.name.split(".")[0] for a in stmt.names]
    return [a.asname or a.name for a in stmt.names]


def tidy(path):
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    lines = src.splitlines()
    tree = ast.parse(src)

    seen = set()
    drop = set()
    for node in tree.body:                       # faqat modul darajasidagi
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        names = set(bound_names(node))
        if names & seen:                         # allaqachon binding qilingan
            if names <= seen:
                drop.update(range(node.lineno - 1, node.end_lineno))
        seen |= names

    if not drop:
        return 0
    out = [l for i, l in enumerate(lines) if i not in drop]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out).rstrip() + "\n")
    return len(drop)


def main():
    total = 0
    for name in sorted(os.listdir(REPOS)):
        if not name.endswith(".py") or name == "__init__.py":
            continue
        n = tidy(os.path.join(REPOS, name))
        if n:
            print(f"  {name:26s} {n} takror import qatori olib tashlandi")
            total += n
    print("JAMI:", total, "qator tozalandi" if total else "(tozalash kerak emas)")


if __name__ == "__main__":
    sys.exit(main())
