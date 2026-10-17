"""Premium (custom) emoji: foydalanuvchi xabaridagi ``custom_emoji`` entity'larini ``<tg-emoji>`` tegiga aylantiradi.

Telegram qoidasi: bot custom emoji'ni FAQAT Fragment'dan qo'shimcha username sotib olgan bo'lsa yubora oladi.
Shuning uchun yuborish vaqtida teg ``CUSTOM_EMOJI_ENABLED=1`` bo'lgandagina chiqadi (``telegram_sanitizer``);
o'chiq bo'lsa teg olib tashlanadi, oddiy emoji (zaxira belgi) qoladi — post har holda chiqadi.
"""
from __future__ import annotations

import os
import re

_ID_RE = re.compile(r"\d{1,32}\Z")


def enabled() -> bool:
    return os.getenv("CUSTOM_EMOJI_ENABLED", "0").strip() == "1"


def text_with_custom_emoji(text, entities) -> str:
    """``text`` dagi custom_emoji entity'lari ``<tg-emoji emoji-id="..">belgi</tg-emoji>`` bo'ladi; qolgan matn O'ZGARMAYDI.

    Offset/uzunliklar UTF-16 birligida (Telegram). Entity bo'lmasa yoki yaroqsiz bo'lsa matn o'zgarishsiz qaytadi.
    """
    raw = "" if text is None else str(text)
    spans = []
    for ent in entities or []:
        if str(getattr(ent, "type", "")) != "custom_emoji":
            continue
        emoji_id = str(getattr(ent, "custom_emoji_id", "") or "")
        try:
            start, length = int(ent.offset), int(ent.length)
        except (TypeError, ValueError, AttributeError):
            continue
        if _ID_RE.match(emoji_id) and start >= 0 and length > 0:
            spans.append((start, start + length, emoji_id))
    if not spans:
        return raw
    units = raw.encode("utf-16-le")
    out, pos = [], 0
    for start, end, emoji_id in sorted(spans):
        if start < pos or end * 2 > len(units):
            continue  # ustma-ust yoki chegaradan chiqqan entity e'tiborsiz
        out.append(units[pos * 2:start * 2].decode("utf-16-le", "ignore"))
        inner = units[start * 2:end * 2].decode("utf-16-le", "ignore")
        out.append(f'<tg-emoji emoji-id="{emoji_id}">{inner}</tg-emoji>')
        pos = end
    out.append(units[pos * 2:].decode("utf-16-le", "ignore"))
    return "".join(out)
