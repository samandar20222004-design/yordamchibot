#!/usr/bin/env bash
# Barcha testlarni ishga tushirish:
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
echo "==================== LOAD TEST ======================"
if "$PY" -c "import pgserver" 2>/dev/null; then
    "$PY" tests/load_test.py || exit 1
else
    echo "pgserver topilmadi — load-test o'tkazib yuboriladi (pip install pgserver)."
fi

echo
echo "BARCHA TESTLAR MUVOFFAQIYATLI ✔"
