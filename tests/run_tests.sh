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
#   3g) 📊 STATISTIKA + ⚙️ SOZLAMALAR + ⚙️ ADMIN PANEL RBAC —
#       PostAssist V2 5-qadam (tests/settings_and_stats_v2_test.py)
#   3h) 🗓 SMART CONTENT CALENDAR — 7/30 kunlik reja, PRO entitlement,
#       haftalik limit, Magic Post uzatmasi, i18n va xavfsizlik
#       (tests/content_calendar_flow_test.py)
#   3i) 🔄 POSTASSIST V2 2-QADAM REFAKTORI — B1 (navbat) + B2 (rasm) birlashtiruvi
#       (tests/refactor_step2_test.py)
#   3j) ⚙️ POSTASSIST V2 3-QADAM REFAKTORI — sozlamalar menyusi (legacy
#       dublikatlarsiz, 8 guruh + rewards/help hub) + 🧰 Vositalar submenyusi
#       (Konvertor va Post Enhancer) (tests/refactor_step3_test.py)
#   3l) 🏁 YAKUNIY ACCEPTANCE SUITE — TEST A..AF (32 ta qat'iy tekshiruv):
#       6-tugma menyu, submenu pariteti, navigatsiya stacki, statistika
#       izolyatsiyasi, dublikat yo'qligi, RBAC tampering himoyasi va i18n
#       sinxroni (tests/final_acceptance_suite_test.py)
#   3m) 📊 STATISTIKA IZOLYATSIYASI — asosiy menyu «📊 Statistika» FAQAT
#       shaxsiy hisobot; admin (bot bo'yicha) statistikasi faqat
#       ⚙️ Admin Panel → «📊 To'liq statistika»
#       (tests/statistics_isolation_test.py)
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
echo "===== 3g) 📊 STATISTIKA + ⚙️ SOZLAMALAR + ADMIN RBAC ====="
# (1) 📊 Statistika — aniq nom + ixcham 4 ko'rsatkich (📢 kanallar /
# 📝 yaratilgan postlar / 📅 rejalashtirilgan / 🤖 AI so'rovlar & kreditlar)
# va natija ostida [🔄 Yangilash] [◀️ Orqaga]; (2) ⚙️ Sozlamalar — yagona
# tartibli menyu: 8 ta guruh (👤 Profil / 🌐 Til / 🎁 Bonuslar & Ballar /
# 🎨 Post sozlamalari / 🔔 Bildirishnomalar / 💳 To'lovlar tarixi /
# 🧰 Vositalar / ❓ Yordam & Ma'lumot) + [◀️ Orqaga]; (3) ⚙️ Admin Panel — oddiy
# foydalanuvchiga MUTLAQO yopiq (RBAC fail-closed), admin kirganda tizim
# monitoringi (Bot & DB / Scheduler / AI provayderlar / Pending manual
# to'lovlar); (4) translations/settings_stats.py UZ/RU/EN 100% paritet;
# (5) regressiya qo'riqonlari (6-tugma menyu, FSM, eski callback'lar)
# (tests/settings_and_stats_v2_test.py).
"$PY" tests/settings_and_stats_v2_test.py || EXIT_CODE=1

echo
echo "===== 3h) 🗓 SMART CONTENT CALENDAR (7/30 KUNLIK REJA) ====="
# (1) FREE 7 kunlik reja tuza oladi, 30 kunlik reja FAQAT PRO
# (pro_required), noto'g'ri davomiylik rad etiladi (invalid_duration);
# (2) FREE da haftasiga 1 ta 7 kunlik reja (weekly_limit);
# (3) tanlangan kun mavzusi «✨ Magic Post» oqimiga aynan uzatiladi;
# (4) translations/content_calendar.py UZ/RU/EN 100% paritet;
# (5) xavfsizlik: entitlement DB xatosida FAIL-CLOSED, AI javobi faqat
# lug'at shaklida va kunlar soni bilan cheklangan, ishonchsiz matn
# HTML-escape qilinadi (tests/content_calendar_flow_test.py).
"$PY" tests/content_calendar_flow_test.py || EXIT_CODE=1

echo
echo "===== 3i) 🔄 2-QADAM REFAKTORI: B1 NAVBAT + B2 RASM OQIMI ====="
# (1) «Kutilayotgan postlar» + «Rejalashtirilgan postlar» YAGONA «📅
# Rejalashtirilgan» ekraniga birlashtirildi — har bir post ostida TO'LIQ
# amallar: [👁 Ko'rish] [✏️ Tahrirlash] [⏰ Vaqt] [🔗 Tugma/Reaksiya]
# [🗑 O'chirish] (barchasi mavjud, sinovdan o'tgan oqimlarga ulanadi);
# (2) eski cab_pending / cab_queue callback'lari AYNAN shu yagona ekranga
# xavfsiz yo'naltiriladi — baza xatosida ham foydalanuvchi javob oladi
# (crash yo'q, tugma "qotmaydi"); (3) AI Studio va Onboarding'dagi
# «🖼 Rasmdan post...» tugmalari YAGONA «📸 Rasm → Post» oqimini ochadi
# (IMAGE_POST_INPUT), eski photo_* callback'lari va 408–410 holatlari ALIAS
# sifatida saqlanadi; (4) «🤖 AI Yordamchi» → [🧠 Kontent reja] 7/30 kunlik
# SMART CONTENT CALENDAR oqimini boshlaydi (soha → cal_days:7|30 → AI reja →
# cal_day:N → «✨ Magic Post»), FREE uchun 30 kun PRO taklifiga olib boradi;
# (5) yangi FSM holatlari (470–472) noyob, yangi callback'lar <=64 bayt,
# eskirgan tugmalar toast bilan javob beradi, i18n UZ/RU/EN 100% paritet
# (tests/refactor_step2_test.py).
"$PY" tests/refactor_step2_test.py || EXIT_CODE=1

echo
echo "===== 3j) ⚙️ 3-QADAM REFAKTORI: SOZLAMALAR MENYUSI + VOSITALAR ====="
# (1) ⚙️ Sozlamalar menyusidagi LEGACY DUBLIKATLAR (📢 Mening kanallarim,
# 📊 Analitika, 📅 Kutilayotgan/Rejalashtirilgan, 💎 Ballar & reklama rejimi)
# ko'rinishdan olib tashlandi — ular o'z asosiy menyularida bor; menyu
# yagona, tartibli va TO'LIQ: 8 guruh + [◀️ Orqaga], UZ/RU/EN da AYNAN
# bir xil callback'lar bilan:
#   [👤 Profil] [🌐 Til] / [🎁 Bonuslar & Ballar] [🎨 Post sozlamalari] /
#   [🔔 Bildirishnomalar] [💳 To'lovlar tarixi] /
#   [🧰 Vositalar] [❓ Yordam & Ma'lumot] / [◀️ Orqaga];
# rewards/help ichki hub'lari eski callback aliaslarini ham saqlaydi;
# (2) eski cab_* callback'lari O'CHIRILMAGAN — xavfsiz alias/redirect
# sifatida ishlaydi (crash yo'q); (3) 🧰 Vositalar submenyusi: ilgari
# yashirinib qolgan Konvertor (#38) va Post Enhancer (#9) endi aniq,
# ko'rinadigan joyida — mavjud CONVERT_INPUT / ENH_POST oqimlariga ulanadi;
# (4) 🔄 Ballar o'tkazish menyudan ham mavjud TRANSFER_TARGET →
# TRANSFER_AMOUNT FSM oqimini ochadi; (5) i18n UZ/RU/EN 100% paritet
# (in_sync: True) va barcha callback'lar 64-bayt chegarasida
# (tests/refactor_step3_test.py).
"$PY" tests/refactor_step3_test.py || EXIT_CODE=1

echo
echo "===== 3k) 🧭 4-QADAM REFAKTORI: NAVIGATSIYA STACKI + ADMIN DASHBOARD ====="
# (1) Navigatsiya stacki: Kontent → AI Yordamchi → [◀️ Orqaga] → Kontent
#     yaratish submenyusi (asosiy menyuga sakramaydi); Kanallarim → Kanal →
#     [◀️ Orqaga] → kanallar ro'yxati; Sozlamalar → Vositalar → [◀️ Orqaga] →
#     Sozlamalar menyusi; (2) ◀️ Orqaga / ❌ Bekor qilish / 🏠 Asosiy menyu
#     mantig'i ajratildi — FSM ichida Bekor qilish kontekstni tozalanib
#     O'SHA BO'LIM BOSHIGA qaytadi, oddiy ko'rishda Orqaga parent menyuga;
#     (3) 👑 Admin dashboard YAGONA MARKAZ: 12 tugma (adm_posts, adm_tag,
#     adm_ai, adm_dbcache, adm_audit_roles, adm_health ...) faqat adminga
#     ochiladi, dublikat statistika handlerlari bitta ekranga birlashdi,
#     eski reply-tugmalar/buyruqlar alias sifatida ishlaydi; (4) oddiy
#     foydalanuvchiga BARCHA adm_* callback'lari qat'iy yopiq (tampering,
#     fail-closed, server-side RBAC); (5) i18n UZ/RU/EN 100% paritet va
#     callback'lar 64-bayt chegarasida
#     (tests/refactor_step4_test.py).
"$PY" tests/refactor_step4_test.py || EXIT_CODE=1

echo
echo "===== 3l) 🏁 YAKUNIY ACCEPTANCE SUITE (TEST A..AF — 32 TEKSHIRUV) ====="
# Loyihadagi BARCHA majburiy tekshiruvlar bitta qabul yuzasida:
# (A..D) asosiy menyu QAT'IY 6 tugma UZ/RU/EN; (E..G) Kontent va AI Studio
# submenu pariteti (in_sync: True); (H..J) Kanallarim + Rejalashtirilgan
# navigatsiyasi; (K..N) 📊 Statistika — FAQAT shaxsiy hisobot (ADMIN
# STATISTIKASI IZOLYATSIYASI), ⚙️ Sozlamalar 8 guruh + Orqaga, 💎 PRO, 🧰 Vositalar;
# (O) ko'rinadigan menyularda dublikat yo'q; (P..S) har bir tugma ishchi
# handler/callback'ga ega (uchala tilda); (T..V) Back/Cancel/Exit stacki;
# (W..X) eski tugma va callback'lar (backward compatibility); (Y) FSM
# holatlari konfliktsiz; (Z..AB) ACTION-FIRST rasm/ovoz/uzun matn;
# (AC..AD) Admin panel oddiy foydalanuvchiga 100% yopiq + server-side RBAC
# tampering himoyasi; (AE..AF) barcha matnlar i18n orqali va 3 tilda 100%
# sinxron (tests/final_acceptance_suite_test.py).
"$PY" tests/final_acceptance_suite_test.py || EXIT_CODE=1

echo
echo "===== 3m) 📊 STATISTIKA IZOLYATSIYASI (SHAXSIY vs ADMIN) ====="
# Asosiy menyudagi «📊 Statistika» (uz/ru/en) FAQAT shaxsiy hisobotni
# ochadi — admin bo'ladimi, oddiy foydalanuvchimi, ADMIN PANEL
# statistikasi («Jami foydalanuvchilar», «Homiy kanallar», «Bekor
# qilingan postlar») HECH QACHON chiqmaydi:
# (1) oddiy user va ADMIN uchun ham get_system_stats CHAQIRILMAYDI;
# (2) ekranda FAQAT foydalanuvchining O'Z ma'lumotlari (📢 ulangan
# kanallaringiz / 📝 yaratilgan postlaringiz / 📅 rejalashtirilgan
# postlar / 💎 qolgan AI kreditlaringiz);
# (3) tugmalar [📈 Kanal bo'yicha batafsil] [◀️ Orqaga] (an_detail/an_close)
# va an_overview kanal analitikasidan shaxsiy statistikaga qaytaradi;
# (4) admin (bot bo'yichi) statistikasi FAQAT ⚙️ Admin Panel →
# «📊 To'liq statistika» ichida (yagona egalik, kesishuvchi yorliq yo'q);
# (5) UZ/RU/EN 100% paritet + haqiqiy router routing qo'riqonlari
# (tests/statistics_isolation_test.py).
"$PY" tests/statistics_isolation_test.py || EXIT_CODE=1

echo
echo "======== 4) TO'LIQ REGRESSIYA (telegram_bot/tests) ========"
# PY'ni aniq uzatamiz: ichki runner ham shu interpreter (venv) bilan ishlasin.
( cd telegram_bot && PYTHON="$PY" bash tests/run_tests.sh ) || EXIT_CODE=1

echo
echo "=============================================================="
if [ "$EXIT_CODE" -eq 0 ]; then
    echo "BARCHA TESTLAR 100% YASHIL ✔"
else
    echo "XATOLIK: ayrim testlar yiqildi (yuqoridagi [FAIL] qatorlarini ko'ring)."
fi
exit "$EXIT_CODE"
