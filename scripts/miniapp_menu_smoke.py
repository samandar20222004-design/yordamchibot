#!/usr/bin/env python3
"""Telegram «Menu» tugmasi Mini App'ga HAQIQIY Bot API orqali o'rnatilishini tekshirish (qo'lda, TEST bot bilan).

    read -rs MINIAPP_SMOKE_BOT_TOKEN && export MINIAPP_SMOKE_BOT_TOKEN      # TEST bot tokeni, production EMAS
    export MINIAPP_URL=https://<domen>/app/
    python scripts/miniapp_menu_smoke.py            # o'rnatadi, qayta o'qib solishtiradi, so'ng ASL holatga qaytaradi
    python scripts/miniapp_menu_smoke.py --keep     # tugmani Mini App'da QOLDIRADI

Qadamlar: getChatMenuButton (asl holat) -> setChatMenuButton(web_app) -> getChatMenuButton (solishtirish) ->
asl holatni tiklash. Token HECH QACHON chop etilmaydi; faqat tugma turi va URL (maxfiy emas) ko'rsatiladi.
Natija kodi: 0 — Telegram tugmani qabul qildi va qaytarib berdi; 1 — rad/farq; 2 — foydalanish xatosi.
`MINIAPP_SMOKE_API_BASE` — faqat testlar uchun (soxta Bot API serveri).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))


def _describe(button) -> str:
    kind = getattr(button, "type", "?")
    url = getattr(getattr(button, "web_app", None), "url", None)
    return f"{kind}" + (f" ({url})" if url else "")


async def run(token: str, url: str, *, keep: bool = False, api_base: str | None = None, out=print) -> int:
    from miniapp_api.menu import valid_miniapp_url
    from telegram import Bot, MenuButtonDefault, MenuButtonWebApp, WebAppInfo

    if not valid_miniapp_url(url):
        out("MINIAPP_URL yaroqsiz: faqat to'liq https:// manzil.")
        return 2
    bot = Bot(token, base_url=api_base) if api_base else Bot(token)
    try:
        await bot.initialize()
        before = await bot.get_chat_menu_button()
        out(f"1) asl holat: {_describe(before)}")
        wanted = MenuButtonWebApp(text="PostAssist", web_app=WebAppInfo(url=url))
        await bot.set_chat_menu_button(menu_button=wanted)
        after = await bot.get_chat_menu_button()
        out(f"2) o'rnatildi, Telegram qaytardi: {_describe(after)}")
        ok = getattr(after, "type", None) == "web_app" and getattr(after.web_app, "url", None) == url
        out("   moslik: " + ("OK" if ok else "FARQ"))
        if not keep:
            await bot.set_chat_menu_button(menu_button=before if before is not None else MenuButtonDefault())
            restored = await bot.get_chat_menu_button()
            out(f"3) asl holat tiklandi: {_describe(restored)}")
        return 0 if ok else 1
    except Exception as exc:  # noqa: BLE001 — istisno matnida token/URL bo'lishi mumkin
        out(f"Bot API xatosi ({type(exc).__name__}): tugma o'rnatilmadi yoki o'qilmadi.")
        return 1
    finally:
        try:
            await bot.shutdown()
        except Exception:  # noqa: BLE001
            pass


def main(argv: list[str]) -> int:
    keep = "--keep" in argv
    if any(a not in ("--keep",) for a in argv):
        print(__doc__)
        return 2
    token = os.environ.get("MINIAPP_SMOKE_BOT_TOKEN", "")
    url = (os.environ.get("MINIAPP_URL") or "").strip()
    if not token or not url:
        print("MINIAPP_SMOKE_BOT_TOKEN va MINIAPP_URL o'zgaruvchilari kerak.")
        return 2
    return asyncio.run(run(token, url, keep=keep, api_base=os.environ.get("MINIAPP_SMOKE_API_BASE") or None))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
