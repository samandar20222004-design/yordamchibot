"""AST audit for user-facing literals in handlers and keyboards.
The scanner is deliberately conservative: callback data, logging and metadata
are not UI; direct string arguments to Telegram UI methods are reported.
"""
import ast
from pathlib import Path

UI_CALLS = {"reply_text", "answer", "edit_text", "send_message", "InlineKeyboardButton", "KeyboardButton"}

def scan_file(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))
    findings=[]
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call): continue
        name = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func,"id","")
        if name not in UI_CALLS or not n.args: continue
        arg=n.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value,str) and arg.value.strip():
            findings.append((n.lineno, name, arg.value))
    return findings

def scan(root=None):
    root=Path(root or Path(__file__).parents[1])
    files=list((root/'telegram_bot'/'handlers').glob('*.py'))+list((root/'telegram_bot'/'keyboards').glob('*.py'))
    result={}
    for p in files:
        hits=scan_file(p)
        if hits:
            result[str(p)]=hits
    return result

# Stable names for CI and for callers embedding the audit.
find_hardcoded_strings = scan_file
scan_handlers_and_keyboards = scan

if __name__ == '__main__':
    import sys
    print(scan(sys.argv[1] if len(sys.argv)>1 else None))
