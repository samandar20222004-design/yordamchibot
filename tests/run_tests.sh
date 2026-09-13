#!/usr/bin/env bash
# ============================================================================
# PostAssist V2 — YUQORI DARAJA TEST RUNNER (repo ildizi)
#
# Ishga tushirish (repo ildizidan):
#     bash tests/run_tests.sh
#
# Bosqichlar:
#   1) Sintaksis darsi (telegram_bot/tests/syntax_test.py)
#   2) 3-BOSQICH PRODUCTION ACCEPTANCE SUITE — 18 majburiy ssenariy
#      (tests/production_acceptance_suite_test.py — deterministik, mock asosida)
#   3) ✨ MAGIC POST oqimi — Killer Feature #1 (tests/magic_post_flow_test.py)
#   4) TO'LIQ regressiya: telegram_bot/tests/run_tests.sh (barcha 30+ test fayli)
#
# Har qanday xatoda 1 bilan chiqadi (CI uchun).
# ============================================================================
set -u
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
EXIT_CODE=0

echo "=============================================================="
echo " PostAssist V2 — TO'LIQ TEST O'TKAZISH (bash tests/run_tests.sh)"
echo "=============================================================="

echo
echo "==================== 1) SYNTAX TEST ===================="
( cd telegram_bot && "$PY" tests/syntax_test.py ) || EXIT_CODE=1

echo
echo "======= 2) 3-BOSQICH PRODUCTION ACCEPTANCE SUITE (18) ======="
"$PY" tests/production_acceptance_suite_test.py || EXIT_CODE=1

echo
echo "======= 3) ✨ MAGIC POST OQIMI (KILLER FEATURE #1) ======="
# Foydalanuvchi xom matn → 5 uslub menyusi → AI generatsiya (uslubga xos
# tizim prompti) → [Kanalga yuborish] / [Rejalashtirish] / [Boshqa uslub]
# + i18n UZ/RU/EN 100% paritet (tests/magic_post_flow_test.py).
"$PY" tests/magic_post_flow_test.py || EXIT_CODE=1

echo
echo "======= 3b) 🎙 VOICE → POST (STT $0 + RESURS HIMOYASI) ======="
# Ovozli xabar → cheklovlar (FREE ≤60s, PRO ≤180s, ≤20MB) → Groq Whisper
# Large v3 (bepul STT, zaxira Gemini) → 5 uslub + [Bekor qilish] → uslub
# tanlanganda FAQAT 1 kredit atomik → tayyor post + amallar.
# Kredit/limit transkripsiya va bekor qilishda TIYILMAYDI
# (tests/voice_to_post_flow_test.py).
"$PY" tests/voice_to_post_flow_test.py || EXIT_CODE=1

echo
echo "======== 4) TO'LIQ REGRESSIYA (telegram_bot/tests) ========"
( cd telegram_bot && bash tests/run_tests.sh ) || EXIT_CODE=1

echo
echo "=============================================================="
if [ "$EXIT_CODE" -eq 0 ]; then
    echo "BARCHA TESTLAR 100% YASHIL ✔"
else
    echo "XATOLIK: ayrim testlar yiqildi (yuqoridagi [FAIL] qatorlarini ko'ring)."
fi
exit "$EXIT_CODE"
