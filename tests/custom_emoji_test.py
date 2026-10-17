#!/usr/bin/env python3
"""Premium (custom) emoji: entity -> <tg-emoji>, sanitayzer, CUSTOM_EMOJI_ENABLED bayrog'i (o'chiq = oddiy emoji, post ketadi)."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace as N

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

from utils.custom_emoji import enabled, text_with_custom_emoji  # noqa: E402
from utils.telegram_sanitizer import has_allowed_html, sanitize_html, telegram_html_payload  # noqa: E402

OK, BAD = [], []


def check(name, cond, extra=""):
    (OK if cond else BAD).append(name)
    print(("  [OK] " if cond else "  [XATO] ") + name + ("" if cond else f" — {extra}"))


ID = "5368324170671202286"
ent = lambda off, ln, cid=ID, typ="custom_emoji": N(type=typ, offset=off, length=ln, custom_emoji_id=cid)  # noqa: E731


def main():
    print("\n== 1. entity -> <tg-emoji> (UTF-16 offsetlar) ==")
    check("entity yo'q: matn o'zgarmaydi", text_with_custom_emoji("salom <b>x</b>", None) == "salom <b>x</b>")
    check("boshqa turdagi entity e'tiborsiz", text_with_custom_emoji("salom", [ent(0, 5, typ="bold")]) == "salom")
    t = "😀 👍 salom"  # 😀 = 2 UTF-16 birlik
    out = text_with_custom_emoji(t, [ent(3, 2)])
    check("astral emoji'dan keyingi offset to'g'ri", out == f'😀 <tg-emoji emoji-id="{ID}">👍</tg-emoji> salom', out)
    out = text_with_custom_emoji("a👍b👍c", [ent(1, 2), ent(4, 2, cid="77")])
    check("ikkita entity", out == f'a<tg-emoji emoji-id="{ID}">👍</tg-emoji>b<tg-emoji emoji-id="77">👍</tg-emoji>c', out)
    check("yaroqsiz id / chegaradan chiqqan / manfiy offset tashlanadi",
          text_with_custom_emoji("ab", [ent(0, 1, cid="x1"), ent(5, 2), ent(-1, 1)]) == "ab")
    check("ustma-ust entity: birinchisi qoladi", text_with_custom_emoji("👍👍", [ent(0, 2), ent(0, 4)]).count("<tg-emoji") == 1)

    print("\n== 2. sanitayzer va bayroq ==")
    html = f'A <b><tg-emoji emoji-id="{ID}">👍</tg-emoji>x</b>'
    os.environ["CUSTOM_EMOJI_ENABLED"] = "0"
    check("bayroq 0: enabled() False", enabled() is False)
    check("bayroq 0: teg tashlanadi, emoji va format qoladi", sanitize_html(html, 100) == "A <b>👍x</b>", sanitize_html(html, 100))
    check("bayroq 0: telegram_html_payload ham toza", telegram_html_payload(html, 100) == ("A <b>👍x</b>", "HTML"))
    os.environ["CUSTOM_EMOJI_ENABLED"] = "1"
    check("bayroq 1: teg saqlanadi (bold ichida ham)", sanitize_html(html, 100) == html, sanitize_html(html, 100))
    check("tg-emoji ruxsat etilgan teg sifatida tan olinadi", has_allowed_html(html))
    bad = '<tg-emoji emoji-id="abc">👍</tg-emoji>'
    check("yaroqsiz emoji-id: teg yuborilmaydi (matn sifatida ko'rinadi)", "<tg-emoji" not in sanitize_html(bad, 100).replace("&lt;tg-emoji", ""), sanitize_html(bad, 100))
    check("emoji-id'siz teg: yuborilmaydi", "&lt;tg-emoji" in sanitize_html("<tg-emoji>👍</tg-emoji>", 100))
    check("uzunlik: fallback emoji hisobga olinadi (UTF-16)", len(sanitize_html(f'<tg-emoji emoji-id="{ID}">👍</tg-emoji>' * 3, 4)) > 0)
    os.environ["CUSTOM_EMOJI_ENABLED"] = "0"

    print(f"\nJAMI: o'tdi={len(OK)}, xato={len(BAD)}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
