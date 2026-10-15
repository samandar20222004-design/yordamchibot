#!/usr/bin/env python3
"""🖼 Bot albomi: «➕ Yana qo'shish» va «↩️ Faylni o'chir» tugmalari (album_choice:add_more / remove_last).

* add_more: keyingi fayllar albomga vaqt oynasisiz qo'shiladi (10 tagacha), 10 ta bo'lsa aniq ogohlantirish;
* remove_last: oxirgi fayl olib tashlanadi, xabar yangilanadi; 1 ta qolsa yakka mediaga aylanadi;
* kollektor tugagach «yana qo'shish» oynasi yopiladi.
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")
os.environ.setdefault("CARD_NUMBER", "8600060950825589")
os.environ.setdefault("CARD_HOLDER", "Test S.")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

import handlers.new_post as np_mod  # noqa: E402
from handlers.new_post import GET_CONTENT, _recent_draft_items, album_choice_callback  # noqa: E402
from locales.translations import get_text  # noqa: E402

OK, BAD = [], []


def check(name, cond, extra=""):
    (OK if cond else BAD).append(name)
    print(("  [OK] " if cond else "  [XATO] ") + name + ("" if cond else f" — {extra}"))


def items(n):
    return [{"type": "photo", "file_id": f"F{i}", "caption": "Izoh" if i == 0 else ""} for i in range(n)]


def make(n, lang="uz"):
    ud = {"post_type": "album", "file_id": json.dumps(items(n)), "content": "Izoh", "lang": lang}
    msg = SimpleNamespace(reply_text=AsyncMock(), from_user=SimpleNamespace(id=777))
    query = SimpleNamespace(data="", message=msg, answer=AsyncMock(), edit_message_text=AsyncMock(), edit_message_reply_markup=AsyncMock())
    ctx = SimpleNamespace(user_data=ud, bot=SimpleNamespace())
    return ctx, query, msg


def run(ctx, query, action):
    query.data = f"album_choice:{action}"
    upd = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=777), message=None)
    return asyncio.get_event_loop().run_until_complete(album_choice_callback(upd, ctx))


def main():
    asyncio.set_event_loop(asyncio.new_event_loop())
    print("\n== 1. add_more ==")
    ctx, q, msg = make(3)
    state = run(ctx, q, "add_more")
    check("GET_CONTENT holatiga qaytadi", state == GET_CONTENT, str(state))
    check("«yana yuboring» yo'riqnomasi chiqdi", msg.reply_text.await_count == 1 and "10" in msg.reply_text.await_args.args[0])
    check("flag qo'yildi: vaqt oynasisiz albomga qo'shiladi", ctx.user_data.get(np_mod._UD_ADD_MORE) is True)
    seed = _recent_draft_items(ctx, window=0.0)
    check("flag bilan avvalgi 3 fayl yo'qolmaydi (window=0 bo'lsa ham)", [i["file_id"] for i in seed] == ["F0", "F1", "F2"], str(seed))
    ctx.user_data.pop(np_mod._UD_ADD_MORE)
    check("flagsiz va oyna o'tgan: seed bo'sh (eski xulq)", _recent_draft_items(ctx, window=0.0) == [])

    ctx, q, msg = make(10)
    run(ctx, q, "add_more")
    check("10 ta to'lgan: ogohlantirish, flag qo'yilmaydi", ctx.user_data.get(np_mod._UD_ADD_MORE) is None and msg.reply_text.await_count == 1
          and get_text("np_album_limit_notice", "uz", limit=10) in msg.reply_text.await_args.args[0])

    print("\n== 2. remove_last ==")
    ctx, q, msg = make(4)
    state = run(ctx, q, "remove_last")
    left = json.loads(ctx.user_data["file_id"])
    check("oxirgi fayl olib tashlandi (4 -> 3), albom qoladi", state == GET_CONTENT and [i["file_id"] for i in left] == ["F0", "F1", "F2"]
          and ctx.user_data["post_type"] == "album", str(ctx.user_data))
    check("xabar yangilandi: yangi son + tanlov tugmalari", q.edit_message_text.await_count == 1
          and "3" in q.edit_message_text.await_args.args[0] and q.edit_message_text.await_args.kwargs["reply_markup"] is not None)
    check("birinchi fayl captioni saqlandi", left[0]["caption"] == "Izoh")

    ctx, q, msg = make(2)
    state = run(ctx, q, "remove_last")
    check("2 -> 1: albom yakka mediaga aylandi (tugma qo'shish mumkin)", ctx.user_data["post_type"] == "photo" and ctx.user_data["file_id"] == "F0",
          str(ctx.user_data))
    check("tugmalar yashirildi va keyingi qadam (tugma so'rovi) chiqdi", q.edit_message_reply_markup.await_count == 1 and msg.reply_text.await_count >= 2)

    ctx, q, msg = make(1)
    ctx.user_data["post_type"] = "photo"
    ctx.user_data["file_id"] = "F0"
    run(ctx, q, "remove_last")
    check("yakka media bilan remove_last hech narsani buzmaydi", ctx.user_data["file_id"] == "F0" and ctx.user_data["post_type"] == "photo")

    print("\n== 3. tarjimalar va yorliqlar ==")
    for lang in ("uz", "ru", "en"):
        for key in ("btn_album_add_more", "btn_album_undo", "np_album_add_more_prompt", "np_album_undone"):
            val = get_text(key, lang, count=3) if key == "np_album_undone" else get_text(key, lang)
            check(f"[{lang}] {key} mavjud", bool(val) and val != key)
        check(f"[{lang}] tugma yorliqlari <= 18 belgi", len(get_text("btn_album_add_more", lang)) <= 18 and len(get_text("btn_album_undo", lang)) <= 18)

    print(f"\nJAMI: o'tdi={len(OK)}, xato={len(BAD)}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
