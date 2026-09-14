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
#   3a) 📸 IMAGE → POST — Killer Feature #3 (tests/image_to_post_flow_test.py)
#   3b) 🎙 VOICE → POST — Killer Feature #2 (tests/voice_to_post_flow_test.py)
#   3c) 📊 POST SCORE & IMPROVER — Killer Feature #4 (tests/post_score_flow_test.py)
#   3d) 🧭 UX V2 — asosiy menyu qat'iy 6 tugma standarti (tests/ux_v2_main_menu_test.py)
#   3e) 🧩 KONTENT YARATISH submenu + ACTION-FIRST (tests/content_creation_menu_test.py)
#   3f) 📢 KANALLARIM + 📅 REJALASHTIRILGAN — PostAssist V2 4-qadam
#       (tests/channels_and_queue_v2_test.py)
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
echo "======= 3a) 📸 IMAGE → POST (GEMINI VISION + PHOTO SCHEDULER) ======="
# Mock Gemini Vision, 10MB/format guard, style tanlanguncha 0 credit,
# tanlanganda 1 credit va photo+caption delivery/scheduler contract.
"$PY" tests/image_to_post_flow_test.py || EXIT_CODE=1

echo
echo "======= 3b) 🎙 VOICE → POST (STT $0 + RESURS HIMOYASI) ======="
# Ovozli xabar → cheklovlar (FREE ≤60s, PRO ≤180s, ≤20MB) → Groq Whisper
# Large v3 (bepul STT, zaxira Gemini) → 5 uslub + [Bekor qilish] → uslub
# tanlanganda FAQAT 1 kredit atomik → tayyor post + amallar.
# Kredit/limit transkripsiya va bekor qilishda TIYILMAYDI
# (tests/voice_to_post_flow_test.py).
"$PY" tests/voice_to_post_flow_test.py || EXIT_CODE=1

echo
echo "===== 3c) 📊 POST SCORE & IMPROVER (KILLER FEATURE #4) ====="
# Matn → 6 mezon (1-10) + 100 ballik natija + tavsiya (BEPUL, kreditsiz);
# Magic/Voice/Image natijalarida «📊 Baholash» tugmasi; «✨ 95/100 ga
# yaxshilash» bosilganda AI eng sara variantni yozadi va AYNAN 1 kredit
# atomik yechiladi (xatoda refund); bo'sh/yaroqsiz matnda xavfsiz
# ogohlantirish + i18n UZ/RU/EN 100% paritet
# (tests/post_score_flow_test.py).
"$PY" tests/post_score_flow_test.py || EXIT_CODE=1

echo
echo "===== 3d) 🧭 UX V2 — ASOSIY MENYU QAT'IY 6 TUGMA STANDARTI ====="
# (1) Asosiy menyu: [✨ Kontent yaratish] [📢 Kanallarim] / [📅 Rejalashtirilgan]
# [📊 Statistika] / [💎 PRO] [⚙️ Sozlamalar] — FAQAT 6 tugma (uz/ru/en);
# (2) Admin Panel faqat ADMIN_IDS uchun (oddiy foydalanuvchida KO'RINMAydi);
# (3) eski tarqoq tugmalar menyudan olingan, routing'da alias qoladi
# (backward compatibility); (4) STARS_PLANS — yagona manba (config.STARS_PLANS:
# precheckout + PaymentService, shadowing yo'q); (5) /start onboarding 3 tilda.
"$PY" tests/ux_v2_main_menu_test.py || EXIT_CODE=1

echo
echo "===== 3e) 🧩 KONTENT YARATISH SUBMENYUSI + ACTION-FIRST ====="
# [🧩 Kontent yaratish] bosilganda ichki menyu: 5 tugma + ◀️ Orqaga
# (✨ Magic Post / 📝 Matn → Post / 📸 Rasm → Post / 🎙 Ovoz → Post /
# 🤖 AI Yordamchi) — UZ/RU/EN to'liq sinxron, har bir tugma o'z oqimini
# ochadi, ◀️ Orqaga asosiy 6 tugmali menyuga qaytaradi. ACTION-FIRST: menyu
# tashqarisida ovoz → STT, rasm → Vision, xom matn → "✨ Magic Post" taklifi
# (tests/content_creation_menu_test.py).
"$PY" tests/content_creation_menu_test.py || EXIT_CODE=1

echo
echo "===== 3f) 📢 KANALLARIM + 📅 REJALASHTIRILGAN ====="
# (1) [📢 Kanallarim] → ulangan kanallar ro'yxati + [➕ Kanal qo'shish];
# (2) kanal tanlanganda QAT'IY boshqaruv ekrani: [➕ Post yaratish] /
# [📅 Rejalashtirilgan] [📊 Statistika] / [⚙️ Kanal sozlamalari]
# [◀️ Orqaga] — kanal ichidagi amallar asosiy menyuga CHIQIB KETMAYDI;
# (3) [📅 Rejalashtirilgan]: postlar vaqt bo'yicha tartiblangan inline
# ro'yxat ("🕐 Bugun 18:00 — [Matn qisqartmasi]") va har biri ostida
# [✏️ Tahrirlash] [⏰ Vaqtni o'zgartirish] [🗑 O'chirish];
# (4) eskirgan "Postlar navbati" nomi uchala tilda "📅 Rejalashtirilgan"ga
# o'tkazildi, eski yorliqlar routing ALIAS'i bo'lib qoldi; (5) UZ/RU/EN 100%
# paritet + FSM/callback regressiya qo'riqonlari
# (tests/channels_and_queue_v2_test.py).
"$PY" tests/channels_and_queue_v2_test.py || EXIT_CODE=1

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
