# -*- coding: utf-8 -*-
"""SPRINT 1 — ``except ...: pass`` bloklarini structured jurnalga o'tkazuvchi transformator.

Maqsad: production kodida **jimgina yutilgan** xato qolmasin. Skript
AST asosida ishlaydi (regex emas), shuning uchun:
  * faqat body'si AYNAN ``pass`` bo'lgan ``except`` bloklari o'zgartiriladi;
  * mantiq O'ZGARMAYDI — xato avvalgidek yutiladi, faqat jurnal qo'shiladi;
  * kontekst maydonlari (``user_id``, ``channel_id``, ...) faqat
    "xavfsiz bog'langan" (handler ishga tushganda aniq mavjud) nomlardan
    olinadi — NameError xavfi yo'q.

Ishga tushirish (repo ildizidan)::

    python3 tools/eradicate_silent_excepts.py --dry-run   # hisobot
    python3 tools/eradicate_silent_excepts.py             # qo'llash

Idempotent: ikkinchi marta ishga tushirilsa hech narsa o'zgarmaydi.
"""
from __future__ import annotations

import argparse
import ast
import os
import sys
from typing import Iterable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "telegram_bot")

IMPORT_LINE = "from utils.silent_errors import log_silent_failure"

#: Amal nomiga qo'shiladigan kontekst maydonlari (ustuvorlik tartibida).
PRIORITY_FIELDS = (
    "user_id", "uid", "target_user_id", "channel_id", "chat_id", "post_id",
    "job_id", "payment_id", "order_id", "receipt_id", "ticket_id",
    "source_id", "message_id", "item_id", "correlation_id", "request_id",
    "update_id", "lang", "platform", "provider", "stage",
)
MAX_CONTEXT_FIELDS = 4

#: Bu modullarda xato ERROR darajasida yoziladi (pul / ma'lumot / AI zanjiri).
#: ``*`` bilan tugagan yozuvlar prefiks bo'yicha (papka) mos keladi.
CRITICAL_PREFIXES = (
    "database*",
    "main*",
    "scheduler*",
    "repositories/*",
    "services/delivery/*",
    "services/scheduler_service*",
    "services/payment_service*",
    "services/ai/*",
    "services/ai_engine/*",
    "services/ai_gateway*",
    "services/ai_service*",
    "services/ai_quota*",
    "services/credits_service*",
    "services/subscription_service*",
    "services/promo_service*",
    "services/referral_service*",
    "handlers/payment_receipt*",
    "handlers/subscription*",
    "utils/ai_agent*",
    "utils/telegram_delivery*",
)

#: "Kutilgan" yo'qotishlar — DEBUG darajasi (ixtiyoriy import va h.k.).
EXPECTED_EXCEPTIONS = {"ImportError", "ModuleNotFoundError"}

_SKIP_DIRS = {"tests", "staging", "__pycache__"}


def _iter_files() -> Iterable[str]:
    for dirpath, dirnames, filenames in os.walk(PKG):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def _module_name(path: str) -> str:
    rel = os.path.relpath(path, PKG).replace(os.sep, "/")
    return rel[:-3].replace("/", ".")


def _is_critical(module: str) -> bool:
    for pattern in CRITICAL_PREFIXES:
        if pattern.endswith("*"):
            if module.startswith(pattern[:-1]):
                return True
        elif module == pattern:
            return True
    return False


class _Scope:
    """Funksiya ichidagi AST tugunlari uchun ota-ona zanjiri + xavfsiz nomlar."""

    def __init__(self, fn: ast.AST, tree: ast.AST):
        self.fn = fn
        self.parent: dict[int, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                self.parent[id(child)] = node

    def _chain(self, node: ast.AST) -> tuple[int, ...]:
        """Funksiyagacha bo'lgan konteynerlar zanjiri (node o'zi kirmaydi)."""
        chain: list[int] = []
        current = self.parent.get(id(node))
        while current is not None and current is not self.fn:
            chain.append(id(current))
            current = self.parent.get(id(current))
        return tuple(reversed(chain))

    def _same_block_and_before(self, node: ast.AST, try_node: ast.AST) -> bool:
        if self._chain(node) != self._chain(try_node):
            return False
        return (getattr(node, "lineno", 0), getattr(node, "col_offset", 0)) < (
            getattr(try_node, "lineno", 0), getattr(try_node, "col_offset", 0),
        )

    def _bound_names(self, target: ast.AST) -> set[str]:
        names: set[str] = set()
        for node in ast.walk(target):
            if isinstance(node, ast.Name):
                names.add(node.id)
        return names

    def safe_names(self, try_node: ast.AST) -> set[str]:
        """Handler ishga tushganda MAVJUD bo'lishi kafolatlangan nomlar."""
        names: set[str] = set()
        args = getattr(self.fn, "args", None)
        if args is not None:
            for arg in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
                names.add(arg.arg)
            if args.vararg:
                names.add(args.vararg.arg)
            if args.kwarg:
                names.add(args.kwarg.arg)

        pending = list(ast.iter_child_nodes(self.fn))
        for node in pending:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                continue  # ichki scope'ga kirmaymiz
            pending.extend(ast.iter_child_nodes(node))
            if not self._same_block_and_before(node, try_node):
                continue
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    names |= self._bound_names(target)
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                names |= self._bound_names(node.target)
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                names |= self._bound_names(node.target)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if item.optional_vars is not None:
                        names |= self._bound_names(item.optional_vars)
            elif isinstance(node, ast.NamedExpr):
                names |= self._bound_names(node.target)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                names.add(node.name)
        return names


def _exception_names(handler: ast.ExceptHandler) -> set[str]:
    exc_type = handler.type
    if exc_type is None:
        return {"BaseException"}
    if isinstance(exc_type, ast.Tuple):
        return {
            elt.id for elt in exc_type.elts
            if isinstance(elt, ast.Name)
        } | {
            elt.attr for elt in exc_type.elts
            if isinstance(elt, ast.Attribute)
        }
    if isinstance(exc_type, ast.Name):
        return {exc_type.id}
    if isinstance(exc_type, ast.Attribute):
        return {exc_type.attr}
    return set()


def _qualname(fn_stack: list[str]) -> str:
    return ".".join(fn_stack) if fn_stack else "<module>"


def _build_call(action: str, exc_name: str, context: list[str], level: str) -> str:
    parts = [f'"{action}"', exc_name]
    if level == "debug":
        parts.append("expected=True")
    parts.extend(f"{name}={name}" for name in context)
    return "log_silent_failure(" + ", ".join(parts) + ")"


def transform(path: str, dry_run: bool = False) -> tuple[int, list[str]]:
    """Faylni o'zgartiradi; ``(o'zgarishlar soni, izohlar)`` qaytaradi."""
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    if "log_silent_failure(" in src:
        return 0, []
    tree = ast.parse(src)
    module = _module_name(path)
    notes: list[str] = []

    fn_stack: list[str] = []
    targets: list[tuple[ast.ExceptHandler, ast.Try, _Scope, str]] = []

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node):  # noqa: N802
            fn_stack.append(node.name)
            self.generic_visit(node)
            fn_stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node):  # noqa: N802
            fn_stack.append(node.name)
            self.generic_visit(node)
            fn_stack.pop()

        def visit_Try(self, node):  # noqa: N802
            for handler in node.handlers:
                if len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
                    fn = self._enclosing_fn(node) or tree
                    scope = _Scope(fn, tree)
                    targets.append((handler, node, scope, _qualname(fn_stack)))
            self.generic_visit(node)

        def _enclosing_fn(self, node):
            current = self.parent.get(id(node))
            while current is not None:
                if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    return current
                current = self.parent.get(id(current))
            return None

    Visitor.parent = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            Visitor.parent[id(child)] = node
    Visitor().visit(tree)

    if not targets:
        return 0, []

    lines = src.splitlines()
    per_function: dict[str, int] = {}
    for handler, _try, _scope, qual in targets:
        per_function[qual] = per_function.get(qual, 0) + 1

    edits: list[tuple[int, str]] = []          # (0-based line, yangi matn)
    for handler, try_node, scope, qual in targets:
        pass_line = handler.body[0].lineno - 1
        indent = lines[pass_line][: len(lines[pass_line]) - len(lines[pass_line].lstrip())]
        pass_body = lines[pass_line].strip()
        assert pass_body.startswith("pass"), lines[pass_line]
        # ``pass  # izoh`` ko'rinishidagi izohni saqlab qolamiz.
        trailing_comment = pass_body[len("pass"):].strip()

        # 1) Xato nomi: mavjud bo'lsa o'sha, aks holda yangi qo'shamiz.
        exc_name = handler.name
        if not exc_name:
            exc_name = "_silent_exc"
            header_line = handler.lineno - 1
            header = lines[header_line]
            stripped = header.rstrip()
            comment = ""
            if "#" in stripped:
                code, comment = stripped.split("#", 1)
                comment = "  #" + comment
                stripped = code.rstrip()
            assert stripped.endswith(":"), header
            lines[header_line] = stripped[:-1] + f" as {exc_name}:" + comment

        # 2) Kontekst maydonlari — faqat xavfsiz bog'langan nomlar.
        safe = scope.safe_names(try_node)
        context = [name for name in PRIORITY_FIELDS if name in safe][:MAX_CONTEXT_FIELDS]

        # 3) Amal nomi (+ bir funksiyada bir nechta blok bo'lsa qator raqami).
        action = f"{module}:{qual}"
        if per_function.get(qual, 0) > 1:
            action = f"{action}:{handler.lineno}"

        exc_names = _exception_names(handler)
        expected = bool(exc_names) and exc_names <= EXPECTED_EXCEPTIONS
        level = "debug" if expected else ("error" if _is_critical(module) else "warning")

        call = _build_call(action, exc_name, context, level)
        replacement = f"{indent}{call}"
        if trailing_comment:
            replacement = f"{replacement}  {trailing_comment}"
        edits.append((pass_line, replacement))
        notes.append(f"{module}:{handler.lineno} → {level.upper()} {action}")

    if dry_run:
        return len(edits), notes

    for lineno, text in sorted(edits, reverse=True):
        lines[lineno] = text

    if IMPORT_LINE not in src:
        insert_at = _import_insert_index(tree, lines)
        lines.insert(insert_at, IMPORT_LINE)
        if insert_at < len(lines) and lines[insert_at].strip() != "":
            lines.insert(insert_at + 1, "")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines).rstrip() + "\n")
    return len(edits), notes


def _import_insert_index(tree: ast.Module, lines: list[str]) -> int:
    """Import qatorini kirituvchi indeks (0-based) — sarlavha import blokidan keyin.

    Ko'p qatorli ``from x import (`` bloklarining ICHIGA tushib qolmaslik
    uchun AST ishlatiladi: yetakchi importlar tugagach, birinchi
    "import bo'lmagan" tugundan oldin qo'yamiz.
    """
    last_import_line = 0
    docstring_end = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last_import_line = node.end_lineno or node.lineno
        elif (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str) and last_import_line == 0
                and docstring_end == 0):
            docstring_end = node.end_lineno or node.lineno
        else:
            break
    insert_line = last_import_line or docstring_end  # 1-based; 0 bo'lsa fayl boshi
    insert_at = insert_line
    if insert_at == 0 and lines and lines[0].startswith("#"):
        insert_at = 1  # ``# -*- coding: utf-8 -*-`` qatoridan keyin
    # Chiroyli bo'shliq: import blokidan keyin bo'sh qator qoldiramiz.
    while insert_at < len(lines) and lines[insert_at].strip() == "":
        insert_at += 1
    return insert_at


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--file", help="faqat bitta fayl (repo ildiziga nisbatan)")
    args = parser.parse_args()

    files = [_os.path.join(ROOT, args.file)] if args.file else sorted(_iter_files())
    total = 0
    for path in files:
        changed, notes = transform(path, dry_run=args.dry_run)
        if changed:
            print(f"  {os.path.relpath(path, ROOT):55s} {changed} blok")
            if args.dry_run:
                for note in notes:
                    print(f"      {note}")
            total += changed
    print("JAMI:", total, "(dry-run)" if args.dry_run else "blok yangilandi")
    return 0


_os = os

if __name__ == "__main__":
    sys.exit(main())
