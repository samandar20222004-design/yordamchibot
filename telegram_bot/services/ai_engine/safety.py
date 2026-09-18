"""Trust boundaries. Delimiters are defence in depth, not a model sandbox."""
import html
import os
import re

_LEAK = re.compile(r"you are (?:an? )?(?:gemini|chatgpt|helpful ai)|<system>|\[SYSTEM\]|system (?:prompt|instruction)|(?:api[_ -]?key|secret|token)\s*[:=]\s*\S+|\bsk-[\w-]{16,}|\bAIza[\w-]{25,}|\b\d{8,12}:[\w-]{30,}", re.I)


def untrusted_input(value: str) -> str:
    return '<untrusted_input>' + html.escape(str(value), quote=True) + '</untrusted_input>'


def contains_leak(text: str) -> bool:
    decoded = html.unescape(text)
    if _LEAK.search(decoded):
        return True
    return any(len(v) >= 12 and v in decoded for k, v in os.environ.items()
               if any(s in k.upper() for s in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')))


def sanitize(text: str) -> str:
    from utils.telegram_sanitizer import sanitize_html
    text = re.sub(r'<(script|style|iframe|object)\b[^>]*>.*?</\1\s*>', '', text, flags=re.I | re.S)
    text = re.sub(r'<a\b[^>]*href\s*=\s*[\"\']?\s*(?:javascript|data|vbscript):[^>]*>(.*?)</a\s*>', r'\1', text, flags=re.I | re.S)
    text = re.sub(r'!?\[([^\]]*)\]\(\s*(?:javascript|data|vbscript):[^)]*\)', r'\1', text, flags=re.I)
    return sanitize_html(text, max(4096, len(text) * 6))
