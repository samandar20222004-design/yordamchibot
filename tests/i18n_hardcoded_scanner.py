"""AST audit for hard-coded user-facing text in handlers and keyboards.

The scanner is deliberately conservative: it only inspects direct string
literals passed to known Telegram UI methods. Callback data, logging, and
metadata are not treated as visible UI text.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable


UI_CALLS = frozenset(
    {
        "reply_text",
        "answer",
        "edit_text",
        "send_message",
        "InlineKeyboardButton",
        "KeyboardButton",
    }
)
TEXT_KEYWORDS = frozenset({"text", "label"})
# Bot.send_message takes chat_id before text; the other UI calls take their
# visible text as the first positional argument.
TEXT_POSITION = {"send_message": 1}


def _call_name(call: ast.Call) -> str:
    """Return the callable's simple name for an AST call."""
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return ""


def _literal_text(node: ast.expr) -> str | None:
    """Extract statically known text, including literal parts of an f-string."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        # Keep static portions visible while omitting dynamic expressions.
        text = "".join(
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
        return text or None
    return None


def _text_arguments(call: ast.Call, name: str) -> Iterable[ast.expr]:
    position = TEXT_POSITION.get(name, 0)
    if len(call.args) > position:
        yield call.args[position]
    for keyword in call.keywords:
        if keyword.arg in TEXT_KEYWORDS:
            yield keyword.value


def scan_file(path: str | Path) -> list[tuple[int, str, str]]:
    """Return ``(line, call_name, hard_coded_text)`` findings for one file."""
    path = Path(path)
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    findings = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name not in UI_CALLS:
            continue
        for argument in _text_arguments(node, name):
            text = _literal_text(argument)
            if text and text.strip():
                findings.append((node.lineno, name, text))

    return sorted(findings, key=lambda finding: finding[0])


def scan(root: str | Path | None = None) -> dict[str, list[tuple[int, str, str]]]:
    """Scan ``telegram_bot/handlers`` and ``telegram_bot/keyboards`` under root."""
    root_path = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    source_root = root_path / "telegram_bot"
    files = sorted(
        [*(source_root / "handlers").glob("*.py"), *(source_root / "keyboards").glob("*.py")]
    )
    return {
        str(path): findings
        for path in files
        if (findings := scan_file(path))
    }


# Stable names for CI and callers embedding the audit.
find_hardcoded_strings = scan_file
scan_handlers_and_keyboards = scan


if __name__ == "__main__":
    import sys

    print(scan(sys.argv[1] if len(sys.argv) > 1 else None))
