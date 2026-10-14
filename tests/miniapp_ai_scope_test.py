#!/usr/bin/env python3
"""Mini App AI chaqiruvi foydalanuvchi byudjeti doirasida (`usage_scope`) bajariladi — audit A-1 (DB'siz).

Muammo: bot `main.py` da har update'ni `usage_scope(user_id=...)` ichida bajaradi, Mini App esa yo'q edi: scope=None ->
`admit_ai_request` "doim ruxsat" qaytarib, har-foydalanuvchi byudjeti va `AI_GLOBAL_DAILY_USD` chetlab o'tilardi.
Bu test Mini App `ai_generate` ichida generatsiya paytida scope'da to'g'ri `user_id` borligini, tugagach (xato bo'lsa ham) tiklanishini tekshiradi.
"""
from __future__ import annotations

import asyncio
import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from miniapp_testkit import FAKE_TOKEN, Counter  # noqa: E402

from miniapp_api.errors import ApiError  # noqa: E402
from miniapp_api.settings import load_settings  # noqa: E402
from miniapp_api.writes import PostWriter  # noqa: E402
from services.ai.usage_scope import current_scope  # noqa: E402

T = Counter("MINI APP — AI usage_scope (DB'siz)")
LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(LOOP)


def run(coro):
    return LOOP.run_until_complete(coro)


class FakeService:
    async def authorize(self, user_id):
        return {"is_admin": False, "language": "uz"}


class ScopeAI:
    """generate() paytida contextvar'dagi scope'ni yozib oladi."""

    def __init__(self, exc=None):
        self.seen = []
        self.exc = exc

    async def is_pro(self, user_id):
        return True          # kvota bronisiz yo'l: aynan shu yo'lda byudjet chetlab o'tilardi

    async def reserve(self, user_id):
        return {"allowed": True, "reservation_id": 1}

    def is_balance_reason(self, reason):
        return False

    async def release(self, user_id, reservation_id):
        return None

    async def generate(self, text, style, lang, is_pro):
        scope = current_scope()
        self.seen.append(None if scope is None else scope.user_id)
        if self.exc:
            raise self.exc
        return {"post_text": "AI natija", "style": style}


def writer(ai):
    base = load_settings({"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "test",
                          "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1", "MINIAPP_REQUIRE_HTTPS": "0"})
    return PostWriter(FakeService(), dataclasses.replace(base), ai=ai)


def main() -> int:
    print("\n== AI generatsiya foydalanuvchi scope'ida ==")
    ai = ScopeAI()
    out = run(writer(ai).ai_generate(4242, {"text": "g'oya", "style": "casual"}))
    T.check("generatsiya muvaffaqiyatli", out["text"] == "AI natija")
    T.check("generatsiya paytida scope.user_id = so'rov egasi (byudjet/global limit ishlaydi)", ai.seen == [4242], str(ai.seen))
    T.check("tugagach scope tiklangan (boshqa so'rovga sizmaydi)", current_scope() is None)

    ai = ScopeAI(exc=RuntimeError("boom"))
    try:
        run(writer(ai).ai_generate(4243, {"text": "g'oya", "style": "casual"}))
        code = "OK"
    except ApiError as exc:
        code = exc.code
    T.check("provayder xatosida ham scope bor edi va tiklandi", ai.seen == [4243] and current_scope() is None and code == "ai_unavailable",
            f"{ai.seen} {code}")

    # parallel so'rovlar bir-biriga user_id sizdirmaydi
    async def two():
        a, b = ScopeAI(), ScopeAI()
        await asyncio.gather(writer(a).ai_generate(1, {"text": "x", "style": "casual"}),
                             writer(b).ai_generate(2, {"text": "y", "style": "casual"}))
        return a.seen, b.seen
    sa, sb = run(two())
    T.check("parallel so'rovlarda scope'lar aralashmaydi", sa == [1] and sb == [2], f"{sa} {sb}")
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
