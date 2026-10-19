#!/usr/bin/env python3
"""Oddiy post UX tuzatishlari: ixcham panel, havola qabul qilish (@username/t.me/domen), nishon limiti (DB'siz)."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [XATO] {label} {detail}")


import database as db_mod  # noqa: E402
from handlers.manual_post import _smart_parse_url_button  # noqa: E402
from keyboards.inline import get_manual_compact_panel, get_manual_more_panel  # noqa: E402
from utils.helpers import apply_post_watermark, watermark_fits  # noqa: E402

print("== Havola: @username, t.me, domen, «Matn - havola» ==")
cases = {
    "@mirzachollgagarin": "https://t.me/mirzachollgagarin",
    "t.me/kanal": "https://t.me/kanal",
    "sayt.uz": "https://sayt.uz",
    "https://sayt.uz/a?b=1": "https://sayt.uz/a?b=1",
    "tg://resolve?domain=kanal": "tg://resolve?domain=kanal",
}
for raw, url in cases.items():
    text, got = _smart_parse_url_button(raw)
    check(f"{raw!r} -> {url}", got == url and bool(text), str((text, got)))
t, u = _smart_parse_url_button("Obuna bo'ling - @kanal")
check("«Matn - @kanal» matn saqlanadi", (t, u) == ("Obuna bo'ling", "https://t.me/kanal"), str((t, u)))
t, u = _smart_parse_url_button("A'zo | https://t.me/x")
check("«Matn | havola»", (t, u) == ("A'zo", "https://t.me/x"), str((t, u)))
for bad in ("javascript:alert(1)", "file:///etc/passwd", "salom dunyo", "@ab", "http://localhost/x", "http://127.0.0.1/a"):
    check(f"xavfli/yaroqsiz rad: {bad!r}", _smart_parse_url_button(bad) == (None, None), str(_smart_parse_url_button(bad)))

print("== Navbatdagi postni tahrirlash: @username/t.me qabul, xavfli havola rad ==")
from utils.security import validate_button_url as sec_validate  # noqa: E402
from handlers.new_post import normalize_button_url  # noqa: E402

check("pending: '@kanal' -> https://t.me/kanal", normalize_button_url("@kanal") == "https://t.me/kanal")
check("pending: 't.me/kanal' -> https://t.me/kanal", normalize_button_url("t.me/kanal") == "https://t.me/kanal")
check("xavfli havola utils.security'da rad", not sec_validate("javascript:alert(1)") and not sec_validate("http://127.0.0.1/a"))

print("== Panel: ixcham asosiy + ⚙️ Qo'shimcha ==")
for lang in ("uz", "ru", "en"):
    compact = get_manual_compact_panel(lang)
    labels = [b.text for row in compact.inline_keyboard for b in row]
    cbs = [b.callback_data for row in compact.inline_keyboard for b in row]
    check(f"[{lang}] asosiy panel 5 tugma (3 qator)", len(labels) == 5 and len(compact.inline_keyboard) == 3, str(labels))
    check(f"[{lang}] asosiy panel yorliqlari <= 18 belgi", all(len(x) <= 18 for x in labels), str([x for x in labels if len(x) > 18]))
    check(f"[{lang}] asosiy panelda: hozir, vaqt, qo'shimcha, tahrirlash, bekor",
          cbs == ["mnp_now", "mnp_time", "mnp_delivery", "mnp_edit", "mnp_cancel"], str(cbs))
    more_off = get_manual_more_panel({}, False, lang)
    more_on = get_manual_more_panel({}, True, lang)
    off_labels = [b.text for row in more_off.inline_keyboard for b in row]
    on_labels = [b.text for row in more_on.inline_keyboard for b in row]
    check(f"[{lang}] Qo'shimcha: 24 soat yoqilsa ✅ belgisi chiqadi", on_labels != off_labels and any("✅" in x for x in on_labels) and not any("✅" in x for x in off_labels), str((off_labels, on_labels)))
    mcbs = [b.callback_data for row in more_off.inline_keyboard for b in row]
    check(f"[{lang}] Qo'shimcha: reaksiya, havola, 24 soat, takror, Orqaga",
          all(c in mcbs for c in ("mnp_react", "mnp_url", "mnp_24h", "mnp_repeat", "mnp_mback")), str(mcbs))
    check(f"[{lang}] callback_data <= 64 bayt", all(len(c.encode()) <= 64 for c in cbs + mcbs))

print("== Bepul nishon: matn limitga to'lgan bo'lsa QO'YILMAYDI ==")
BOT = "PostAssistrobot"
check("qisqa matn sig'adi", watermark_fits("Salom", BOT, 1024))
check("1020 belgi / 1024 limit sig'maydi", not watermark_fits("a" * 1020, BOT, 1024))
check("900 belgi / 1024 limit sig'adi", watermark_fits("a" * 900, BOT, 1024))
check("4090 / 4096 sig'maydi", not watermark_fits("a" * 4090, BOT, 4096))
check("limit berilmasa — doim sig'adi (eski xulq)", watermark_fits("a" * 9999, BOT, None))
check("bo'sh matn — sig'adi", watermark_fits("", BOT, 1024))
check("HTML teglar uzunlikka kirmaydi", watermark_fits("<b>" + "a" * 990 + "</b>", BOT, 1024))

_orig = db_mod.run_db


async def _fake(fn, *a, **k):
    if getattr(fn, "__name__", "") == "is_premium":
        return a[0] == 777
    return await _orig(fn, *a, **k)


db_mod.run_db = _fake
LINE = "🤖 @PostAssistrobot"
run = asyncio.run
out = run(apply_post_watermark("Salom", 555, BOT, limit=1024))
check("bepul + sig'adigan matn -> nishon boshida", out.startswith(LINE + "\n\n"), out)
long_txt = "a" * 1020
out = run(apply_post_watermark(long_txt, 555, BOT, limit=1024))
check("bepul + to'lgan matn -> nishon yo'q, matn o'zgarmagan", out == long_txt, out[:40])
out = run(apply_post_watermark(long_txt, 555, BOT))
check("limit berilmasa eski xulq: nishon qo'yiladi", out.startswith(LINE), out[:40])
out = run(apply_post_watermark("Salom", 777, BOT, limit=1024))
check("PRO: nishon yo'q", out == "Salom", out)
out = run(apply_post_watermark("", 555, BOT, limit=1024))
check("bepul + bo'sh matn (rasm): faqat nishon", out == LINE, out)

print(f"\n JAMI: o'tdi={passed}, xato={failed}")
sys.exit(1 if failed else 0)
