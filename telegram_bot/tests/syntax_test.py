#!/usr/bin/env python3
"""Syntax-test: barcha .py fayllar kompilyatsiya qilinadi va import qilinadi.

Ishga tushirish:
    cd telegram_bot && python tests/syntax_test.py
"""
import os
import sys
import py_compile
from pathlib import Path

# Import qilishdan oldin muhit o'zgaruvchilarini sozlash
os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN_FOR_SYNTAX_CHECK")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10000")

ROOT = Path(__file__).resolve().parent.parent  # telegram_bot/
sys.path.insert(0, str(ROOT))

def main():
    failures = 0

    # 1) Barcha fayllarni kompilyatsiya qilish
    print("== 1. Kompilyatsiya (py_compile) ==")
    py_files = sorted(ROOT.rglob("*.py"))
    for f in py_files:
        try:
            py_compile.compile(str(f), doraise=True)
        except py_compile.PyCompileError as e:
            failures += 1
            print(f"  [FAIL] {f.relative_to(ROOT)}: {e}")
    print(f"  {len(py_files)} ta fayl tekshirildi, xato: {failures}")

    # 2) Import qilish (hech qanday runtime xatosi bo'lmasligi uchun)
    print("== 2. Import tekshiruvi ==")
    modules = [
        "config",
        "database",
        "scheduler",
        "main",
        "keyboards.default",
        "keyboards.inline",
        "locales",
        "locales.translations",
        "translations",
        "translations.magic_post",
        "translations.voice_post",
        "translations.post_score",
        # 🧩 KONTENT YARATISH submenu (PostAssist V2) — yangi modullar
        "translations.content_menu",
        # 📢 KANALLARIM + 📅 REJALASHTIRILGAN (PostAssist V2, 4-qadam)
        "translations.channels_queue",
        "keyboards.reply",
        "handlers.content_creation",
        "utils.helpers",
        "utils.converter",
        "utils.ai_agent",
        "utils.audio_transcriber",
        "utils.web_server",
        "handlers",
        "handlers.voice_post",
        "handlers.post_score",
        # 🧰 VOSITALAR submenyusi (PostAssist V2 · 3-qadam) — sozlamalar
        # menyusidagi [🧰 Vositalar] ekranini chizuvchi modul.
        "handlers.tools",
        "handlers.settings",
        "utils.post_scorer",
        # 🔒 PHASE 2 / 1-qadam: kvota + kredit ATOMIK bron/qaytarish qatlami
        # (barcha AI oqimlari shu modul orqali database.reserve_ai_request /
        # refund_ai_request ni chaqiradi).
        "services.ai_quota",
        # 🚀 PHASE 11 & 12: AI ADVANCED SMM FEATURES — 4 ta yangi xizmat va
        # ularning umumiy poydevori (Phase 3 orchestrator + Phase 2 kvota /
        # sanitizer bilan yagona standartda ishlaydi).
        "services.ai.smm_common",
        "services.ai.smm_mock",
        "services.ai.variants",
        "services.ai.repurpose",
        "services.ai.audit",
        "services.ai.planner",
        "services.ai",
    ]
    for mod in modules:
        try:
            __import__(mod)
            print(f"  [OK] {mod}")
        except Exception as e:
            failures += 1
            print(f"  [FAIL] {mod}: {type(e).__name__}: {e}")

    if failures:
        print(f"\nJAMI XATOLAR: {failures}")
        sys.exit(1)
    print("\nBarcha syntax-testlar muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
