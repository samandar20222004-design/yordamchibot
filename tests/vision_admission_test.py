#!/usr/bin/env python3
"""Rasm -> post (legacy `generate_vision_post`) yo'li AI byudjeti/limit ostida (DB'siz) — audit A-2.

Muammo: `handlers/ai_assistant._vision_run` / `_vision_run_variants` to'g'ridan Gemini'ga borardi (`admit_ai_request` yo'q):
foydalanuvchi limiti, `AI_GLOBAL_DAILY_USD` va telemetriya ko'rmasdi; bitta kvota birligiga 3 parallel Gemini chaqiruvi.
Tuzatish: har kirish nuqtasi BITTA admission ichida (3 variant = 1 ruxsat — aks holda parallel-ish limiti o'z variantlarini rad etardi).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456789:TESTMOCKTOKENabcdefghijklmnopqrstu")
os.environ.setdefault("ADMIN_ID", "111")
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


print("== Vision yo'li AI admission ostida (DB'siz) ==")
import handlers.ai_assistant as AA  # noqa: E402
from services.ai import admission as adm  # noqa: E402
from services.ai.usage_scope import usage_scope  # noqa: E402

state = {"admit": 0, "release": 0, "finalize": 0, "gvp": 0, "download": 0, "cleanup": 0}


class FakeAdmission(adm.Admission):
    async def finalize(self):
        state["finalize"] += 1

    def release(self):
        state["release"] += 1


def install(allowed=True, gvp_exc=None):
    for k in state:
        state[k] = 0

    async def fake_admit(prompt, system_instruction="", lang=None):
        state["admit"] += 1
        return FakeAdmission(allowed, "ok" if allowed else "budget", None if allowed else "LIMIT-MATNI")

    async def fake_download(file_id):
        state["download"] += 1
        return "/tmp/fake.jpg"

    def fake_cleanup(path):
        state["cleanup"] += 1

    async def fake_gvp(image_path, extra_prompt="", tone=None, rewrite_context="", timeout=None, lang="uz"):
        state["gvp"] += 1
        if gvp_exc:
            raise gvp_exc
        return {"post_text": f"post-{tone}"}

    adm.admit_ai_request = fake_admit
    AA.download_telegram_media_to_temp = fake_download
    AA.cleanup_temp_media = fake_cleanup
    AA.generate_vision_post = fake_gvp


orig = (adm.admit_ai_request, AA.download_telegram_media_to_temp, AA.cleanup_temp_media, AA.generate_vision_post)
try:
    # 1) rad etilsa: Gemini ham, yuklash ham chaqirilmaydi
    install(allowed=False)
    out = asyncio.run(AA._vision_run("fid", "izoh", lang="uz"))
    check("rad etilganda foydalanuvchi matni qaytadi", isinstance(out, dict) and out.get("error") == "LIMIT-MATNI", str(out))
    check("rad etilganda Gemini chaqirilmadi va rasm yuklanmadi", state["gvp"] == 0 and state["download"] == 0, str(state))

    # 2) ruxsat: AYNAN 1 chaqiruv, 1 finalize, slot bo'shatildi
    install(allowed=True)
    out = asyncio.run(AA._vision_run("fid", "izoh", lang="uz"))
    check("ruxsat berilganda post qaytadi", out == {"post_text": "post-None"}, str(out))
    check("1 admission, 1 Gemini, finalize va release 1 martadan", (state["admit"], state["gvp"], state["finalize"], state["release"]) == (1, 1, 1, 1), str(state))
    check("vaqtinchalik rasm tozalandi", state["cleanup"] == 1, str(state))

    # 3) provayder istisnosi: slot baribir bo'shaydi
    install(allowed=True, gvp_exc=RuntimeError("boom"))
    out = asyncio.run(AA._vision_run("fid", "izoh", lang="uz"))
    check("istisnoda ham release/finalize chaqirildi (slot oqib ketmaydi)", state["release"] == 1 and state["finalize"] == 1, str(state))
    check("istisnoda foydalanuvchiga xato dict", isinstance(out, dict) and "error" in out, str(out))

    # 4) variantlar: 3 ta Gemini, lekin BITTA admission
    install(allowed=True)
    variants, err = asyncio.run(AA._vision_run_variants("fid", "izoh", lang="uz"))
    n = len(AA.PHOTO_VARIANT_STYLES)
    check(f"{n} variant, lekin BITTA admission (parallel-ish limiti o'z variantlarini rad etmaydi)",
          state["gvp"] == n and state["admit"] == 1 and len(variants) == n, f"{state} {variants}")
    check("variantlarda finalize va release 1 martadan", state["finalize"] == 1 and state["release"] == 1, str(state))

    # 5) variantlar rad etilsa
    install(allowed=False)
    variants, err = asyncio.run(AA._vision_run_variants("fid", "izoh", lang="uz"))
    check("rad etilganda variantlar bo'sh, xato matni limitniki, Gemini chaqirilmadi",
          variants == {} and err == "LIMIT-MATNI" and state["gvp"] == 0 and state["download"] == 0, f"{variants} {err} {state}")

    # 6) ichki chaqiruv (suppress_recording) ikki marta hisoblanmaydi
    install(allowed=True)
    with usage_scope(suppress_recording=True):
        asyncio.run(AA._vision_run("fid", "izoh", lang="uz"))
    check("suppress_recording ichida qayta admission YO'Q (ikki marta hisoblash yo'q)", state["admit"] == 0 and state["gvp"] == 1, str(state))
finally:
    adm.admit_ai_request, AA.download_telegram_media_to_temp, AA.cleanup_temp_media, AA.generate_vision_post = orig

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
