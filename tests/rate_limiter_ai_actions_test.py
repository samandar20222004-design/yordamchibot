#!/usr/bin/env python3
"""AUDIT-011: AI generatsiyani ishga tushiradigan callback'lar (plan_regenerate, ext_rewrite, ext_adapt, ap_regen,
ap_refresh, ap_pregen:) `ai` chegarasiga (1 / 4 s) kiradi; ularning NAVIGATSIYA qo'shnilari (ap_back, ap_freq:, ...)
esa BLOKLANMAYDI (callback_data prefiks mosligi qat'iy). DB/Redis talab qilinmaydi (In-Memory backend)."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456789:TESTMOCKTOKENabcdefghijklmnopqrstu")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

from middlewares.rate_limiter import DEFAULT_AI_ACTIONS, RateLimiter  # noqa: E402
from services.cache_backend import MemoryCacheBackend  # noqa: E402

passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [XATO] {label} {detail}")


def upd(data, uid=1):
    return SimpleNamespace(effective_user=SimpleNamespace(id=uid), callback_query=SimpleNamespace(data=data))


AI = ["plan_regenerate", "ext_rewrite", "ext_adapt", "ap_regen", "ap_refresh", "ap_pregen:3",
      "studio_ai_post", "ai_post_retry"]  # oxirgi ikkitasi — avvaldan bor (xulq o'zgarmagan)
NON_AI = ["ap_back", "ap_freq:2", "ap_mode:AUTO", "ap_pview:1", "ap_pdel:2", "ap_papp:1", "ap_pedit:1", "ap_confirm",
          "ap_cancel", "ap_eday:0", "ap_goal:growth", "ap_edit", "ap_force", "plan_refresh", "ext_back", "ext_schedule",
          "ext_edit", "ext_cancel", "ext_refresh"]

print("== AUDIT-011: rate limiter AI action ro'yxati ==")
rl = RateLimiter(backend=MemoryCacheBackend())
for data in AI:
    buckets = [b for b, _ in rl.classify(upd(data))]
    check(f"{data}: 'ai' chegarasiga kiradi", "ai" in buckets, str(buckets))
for data in NON_AI:
    buckets = [b for b, _ in rl.classify(upd(data))]
    check(f"{data}: 'ai' chegarasiga KIRMAYDI (navigatsiya/oddiy tugma bloklanmaydi)", "ai" not in buckets, str(buckets))
for a in ("plan_regenerate", "ext_rewrite", "ext_adapt", "ap_regen", "ap_refresh", "ap_pregen:"):
    check(f"DEFAULT_AI_ACTIONS ichida: {a}", a in DEFAULT_AI_ACTIONS)


async def flow():
    rl2 = RateLimiter(backend=MemoryCacheBackend())
    first = await rl2.evaluate(upd("ap_regen", uid=77))
    second = await rl2.evaluate(upd("plan_regenerate", uid=77))
    other_user = await rl2.evaluate(upd("ap_regen", uid=78))
    nav = await rl2.evaluate(upd("ap_back", uid=79))
    nav2 = await rl2.evaluate(upd("ap_freq:1", uid=79))
    nav3 = await rl2.evaluate(upd("ap_mode:AUTO", uid=79))
    return first, second, other_user, nav, nav2, nav3


first, second, other_user, nav, nav2, nav3 = asyncio.run(flow())
check("1-AI tugma o'tadi", first is None, str(first))
check("4 s ichida 2-AI tugma (boshqa action) CHEKLANADI ('ai' chegarasi)", second is not None and second.bucket == "ai", str(second))
check("boshqa foydalanuvchi ta'sirlanmaydi", other_user is None, str(other_user))
check("navigatsiya tugmalari (ap_back, ap_freq:, ap_mode:) AI chegarasi bilan BLOKLANMAYDI",
      nav is None and nav2 is None and nav3 is None, f"{nav} {nav2} {nav3}")

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
