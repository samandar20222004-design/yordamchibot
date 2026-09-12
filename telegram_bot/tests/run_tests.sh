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
echo "==================== SERVICES TEST ===================="
"$PY" tests/services_test.py || exit 1

echo
echo "================ SCHEDULER SERVICE TEST =============="
"$PY" tests/scheduler_service_test.py || exit 1

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
echo "=============== PREMIUM / EN i18n TEST ==============="
"$PY" tests/premium_i18n_en_test.py || exit 1

echo
echo "========= 3 TILLIK (UZ/RU/EN) + AI TIL PARITETI ========="
# Yangi: lug'atlar pariteti, AI tizim promptlarining tilga moslashuvi va
# til o'zgarganda pastki klaviatura yangilanishi (tests/i18n_ai_parity_test.py).
"$PY" tests/i18n_ai_parity_test.py || exit 1

echo
echo "=========== ACCOUNT & SETTINGS i18n TEST ============"
"$PY" tests/account_settings_i18n_test.py || exit 1

echo
echo "====== REPLY TUGMA FILTRLARI (uz/ru/en) + SANA + PHOTO_CHECK ======"
# Doimiy (reply) klaviatura tugmalari 3 tilda ham taniyladi, sana/vaqt
# foydalanuvchi tilida chiziladi va 📷 rasm moderatsiyasi ham tilga mos.
"$PY" tests/reply_filters_i18n_dates_test.py || exit 1

echo "========= UZ/RU/EN TO'LIQ PARITET AUDITI (i18n_full_parity) ========="
# Yakuniy 3 tillik audit: lug'atlar pariteti (kalitlar + format argumentlari),
# reply tugmalarining real routing'i (3 til → to'g'ri handler) va AI tizim
# promptlariga til qat'iy birikishi (tests/i18n_full_parity_test.py).
"$PY" tests/i18n_full_parity_test.py || exit 1

echo "=============== NEW POST / AI STUDIO i18n TEST ==============="
"$PY" tests/new_post_i18n_test.py || exit 1
"$PY" tests/ai_studio_plan_i18n_test.py || exit 1

echo
echo "==================== SCHEMA TEST ===================="
"$PY" tests/schema_test.py || exit 1

echo
echo "============ DB INTEGRITY TEST (5-BOSQICH) ============"
"$PY" tests/db_integrity_test.py || exit 1

echo
echo "==================== AI MOCK TEST ==================="
"$PY" tests/ai_mock_test.py || exit 1

echo
echo "==================== AI FALLBACK TEST (4-BOSQICH) ================"
"$PY" tests/ai_fallback_test.py || exit 1

echo
echo "============== RBAC & SECURITY TEST (6-BOSQICH) =============="
"$PY" tests/rbac_security_test.py || exit 1

echo
echo "====== HEALTH & MONITORING TEST (7-BOSQICH) ======"
"$PY" tests/health_monitoring_test.py || exit 1

echo
echo "============ CREDITS LEDGER & REFERRAL TEST (8-BOSQICH) =========="
"$PY" tests/credits_referral_test.py || exit 1

echo
echo "==================== P0 CONCURRENCY TEST ============="
if "$PY" -c "import pytest" 2>/dev/null; then
    "$PY" -m pytest tests/p0_concurrency_test.py -q || exit 1
else
    echo "pytest topilmadi — P0 concurrency-test o'tkazib yuboriladi."
fi

echo
echo "==================== LOAD TEST ======================"
if "$PY" -c "import pgserver" 2>/dev/null; then
    "$PY" tests/load_test.py || exit 1
else
    echo "pgserver topilmadi — load-test o'tkazib yuboriladi (pip install pgserver)."
fi

echo
echo "===== STRESS & CONCURRENCY TEST (9-BOSQICH) ====="
# Static qismi (graceful shutdown, cleanup lojikasi) DOIM ishlaydi; real
# PostgreSQL qismi (100 post / 5 worker, 50 parallel credits+referral,
# shutdown simulyatsiyasi, cleanup worker) pgserver bo'lsa bajariladi.
"$PY" tests/stress_concurrency_test.py || exit 1

echo
echo "===== YAKUNIY ACCEPTANCE TEST (10-BOSQICH) ====="
# PostAssist V2 final smoke: 10 bosqichning barcha asosiy kontraktlari
# (payment idempotency, promo atomic redemption, additive extension,
# delivery idempotency, AI fallback, DB integrity, RBAC, health,
# credits ledger, graceful shutdown) + Docker/CI/Sentry infratuzilma.
"$PY" tests/final_acceptance_test.py || exit 1

echo
echo "BARCHA TESTLAR MUVOFFAQIYATLI ✔"
