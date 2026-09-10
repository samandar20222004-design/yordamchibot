#!/usr/bin/env bash
# Barcha testlarni ishga tushirish (global smoke test — 3000+ tekshiruv):
#   cd telegram_bot && bash tests/run_tests.sh
set -u
cd "$(dirname "$0")/.."

PY=${PYTHON:-python3}
echo "==================== SYNTAX TEST ===================="
"$PY" tests/syntax_test.py || exit 1

echo
echo "==================== UNIT TEST ======================"
"$PY" tests/unit_test.py || exit 1

echo
echo "================ NEW REQUIREMENTS TEST ==============="
"$PY" tests/new_requirements_test.py || exit 1

echo
echo "================= ALBOM & SKIP TEST ================="
"$PY" tests/album_skip_test.py || exit 1

echo "=========== ALBOM OG'HOHLANTIRISH + TOZA KANAL ==========="
"$PY" tests/album_warning_test.py || exit 1

echo "================= PHOTO LEAK & VOICE TEST ===================="
"$PY" tests/photo_leak_test.py || exit 1

echo
echo "================= STICKER REACTION TEST ================="
"$PY" tests/sticker_reaction_test.py || exit 1

echo
echo "================= NEW POST i18n TEST ================"
"$PY" tests/new_post_i18n_test.py || exit 1

echo
echo "============= ACCOUNT & SETTINGS i18n TEST ==========="
"$PY" tests/account_settings_i18n_test.py || exit 1

echo
echo "============== AI STUDIO PLAN i18n TEST ============="
"$PY" tests/ai_studio_plan_i18n_test.py || exit 1

echo
echo "=============== PREMIUM / EN i18n TEST ==============="
"$PY" tests/premium_i18n_en_test.py || exit 1

echo
echo "=========== EXTRAS / ONBOARDING i18n TEST ==========="
"$PY" tests/extras_onboarding_i18n_test.py || exit 1

echo
echo "================= CHANNEL READER TEST ==============="
"$PY" tests/channel_reader_test.py || exit 1

echo
echo "================== FREE vs PRO TEST ================="
"$PY" tests/free_vs_pro_test.py || exit 1

echo
echo "=============== CALLBACK THROTTLE TEST =============="
"$PY" tests/callback_throttle_test.py || exit 1

echo
echo "==================== SCHEMA TEST ===================="
"$PY" tests/schema_test.py || exit 1

echo
echo "==================== AI MOCK TEST ==================="
"$PY" tests/ai_mock_test.py || exit 1

echo
echo "==================== LOAD TEST ======================"
if "$PY" -c "import pgserver" 2>/dev/null; then
    "$PY" tests/load_test.py || exit 1
else
    echo "pgserver topilmadi — load-test o'tkazib yuboriladi (pip install pgserver)."
fi

echo
echo "BARCHA TESTLAR MUVOFFAQIYATLI ✔"
