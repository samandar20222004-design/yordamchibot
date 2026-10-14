#!/usr/bin/env python3
"""Mini App «Menu» tugmasi: faqat yoqilgan + to'g'ri HTTPS URL bo'lsa; aks holda fallback (bot xulqi o'zgarmaydi)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from miniapp_testkit import FAKE_TOKEN, Counter  # noqa: E402

from miniapp_api.menu import miniapp_menu_button, valid_miniapp_url  # noqa: E402

T = Counter("MINI APP — Menu tugmasi (MINIAPP_URL)")
BASE = {"BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "test", "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1"}


def main() -> int:
    ok = {**BASE, "MINIAPP_ENABLED": "1", "MINIAPP_URL": "https://bot.example.com/app/"}
    btn = miniapp_menu_button(ok)
    T.check("yoqilgan + to'g'ri URL -> MenuButtonWebApp",
            btn is not None and btn.web_app.url == "https://bot.example.com/app/" and btn.type == "web_app")
    T.check("MINIAPP_ENABLED=0 (sukut) -> None", miniapp_menu_button({**ok, "MINIAPP_ENABLED": "0"}) is None)
    T.check("MINIAPP_ENABLED yo'q -> None", miniapp_menu_button({k: v for k, v in ok.items() if k != "MINIAPP_ENABLED"}) is None)
    T.check("MINIAPP_URL yo'q -> None", miniapp_menu_button({k: v for k, v in ok.items() if k != "MINIAPP_URL"}) is None)
    T.check("xavfsiz bo'lmagan konfiguratsiya (token yo'q) -> None", miniapp_menu_button({**ok, "BOT_TOKEN": ""}) is None)
    for bad in ("http://bot.example.com/app/", "ftp://x.y/z", "javascript:alert(1)", "https://", "https://user:pw@x.example.com/",
                "https://bot.example.com/a b", "https://bot.example.com/<x>", "//bot.example.com", "bot.example.com",
                "https://" + "a" * 600 + ".com", "https://x.example.com/\x00", "https://localhost x"):
        T.check(f"yaroqsiz URL rad: {bad[:40]!r}", not valid_miniapp_url(bad) and miniapp_menu_button({**ok, "MINIAPP_URL": bad}) is None)
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
