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
#   3a') 📸 IMAGE → POST 3-BOSQICH — Vision fallback + caption extraction
#        (tests/image_post_fallback_test.py)
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
#   3n) ✨ 2-BOSQICH AI PROMPT VA MAGIC POST SIFATI — prompt validation,
#       sifat validatori, yupqa javobda qayta urinish, ixcham UI
#       (tests/ai_prompt_quality_test.py)
#   3l) 🏁 YAKUNIY ACCEPTANCE SUITE — TEST A..AG (33 ta qat'iy tekshiruv):
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
echo "======= 3a') 📸 IMAGE → POST — 3-BOSQICH VISION FALLBACK + CAPTION ======="
# Vision model zanjiri (retired 1.5 yo'q, 404/429/timeout → keyingi model),
# Vision xatosida QURUQ XATO YO'Q: caption → Magic Post generatori, caption
# bo'lmasa muloyim mavzu so'rovi (IMAGE_TOPIC_INPUT); forward/caption
# extraction; natijada Magic Post bilan bir xil ixcham tugmalar; i18n paritet.
"$PY" tests/image_post_fallback_test.py || EXIT_CODE=1

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
echo "===== 3k) 🧭 4-QADAM + 3-BOSQICH: NAVIGATSIYA + YAGONA INLINE ADMIN PANEL ====="
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
#     callback'lar 64-bayt chegarasida.
#     🆕 3-BOSQICH (yagona inline admin panel): pastdagi oq 10 talik ADMIN
#     REPLY-KLAVIATURASI BUTUNLAY olib tashlandi
#     (get_admin_panel_keyboard() → ReplyKeyboardRemove); yagona panel
#     layouti [📊 Bot statistikasi] [📢 Ommaviy xabar] / [🎯 Reklama
#     markazi] [📋 Kanallar ro'yxati] / [📋 Barcha postlar] [🎁 Promo-kod
#     yaratish] / [⭐️ PRO berish] [🏷 Post nishoni] / [⚙️ AI parametrlari]
#     [🗄️ DB / Kesh holati] / [🩺 Tizim monitoringi] [❌ Yopish] — 12 tugma.
#     Eski admin matnlari (Majburiy obuna, AI parametrlar, DB/Kesh ...)
#     FAQAT routing ALIAS'i: chat tarixidan yozilsa ishlaydi, lekin hech
#     qanday klaviaturada chizilmaydi; «📜 Audit | 👥 Rollar» esa
#     🩺 Tizim monitoringi ekraniga ko'chirildi
#     (tests/refactor_step4_test.py → TEST 3/3b).
"$PY" tests/refactor_step4_test.py || EXIT_CODE=1

echo
echo "===== 3l) 🏁 YAKUNIY ACCEPTANCE SUITE (TEST A..AG — 33 TEKSHIRUV) ====="
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
# sinxron; 🆕 (AG) ADMIN PANEL — FAQAT YAGONA INLINE PANEL: eski reply
# klaviatura qaytmaydi, layout 12 tugma (6 qator × 2), barcha adm_*
# tugmalari adminga ishlaydi, RBAC oddiy foydalanuvchini yopadi
# (tests/final_acceptance_suite_test.py).
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
echo "===== 3n) ✨ 2-BOSQICH: AI PROMPT VA MAGIC POST SIFATI ====="
# (1) 5 uslub × 3 til tizim promptlarida MAJBURIY tuzilma: Hook (qalin
# sarlavha + emoji) / Asosiy mazmun (2-4 punkt) / CTA / 3-5 hashtag, «1-2
# qatorli quruq jumla» va so'zma-so'z tarjima TAQIQI, uslublar real farqli
# (Sotuv=AIDA/PAS, Informativ=faktlar+ekspert xulosasi, Premium=lakonik,
# Oddiy=blogerona hayotiy misollar); (2) magic_post_quality_report —
# generatsiya qilingan post uzunligi, sarlavha, CTA va hashtag tekshiruvi;
# (3) generate_magic_post yupqa javobda kuchaytirilgan ko'rsatma bilan BIR
# MARTA qayta so'raydi; (4) ixcham mp_intro (SaaS taklifi) + natija
# klaviaturasi faqat 5 amal [2,2,1]; (5) FSM/callback regressiya, Magic Post
# ichida ovoz/rasm o'z oqimiga yo'naltiriladi (tests/ai_prompt_quality_test.py).
"$PY" tests/ai_prompt_quality_test.py || EXIT_CODE=1

echo
echo "===== 3o) 🔒 PHASE 2 / 1-QADAM: ATOMIK KVOTA + KREDIT TRANZAKSIYASI ====="
# (1) reserve_ai_request(): kunlik kvota YOKI kredit BITTA tranzaksiyada
#     (SELECT ... FOR UPDATE qator qulfi + credits_ledger auditi +
#     ai_reservations bron qatori) — check_ai_limit/use_user_credit
#     juftligining atomar o'rnini bosadi;
# (2) RACE CONDITION: balansda 1 kredit bo'lganda 5 PARALLEL so'rov →
#     AYNAN 1 ta ruxsat, 4 tasi rad; kunlik kvota 3 bo'lganda 5 parallel →
#     AYNAN 3 ta ruxsat (sanagich limitdan oshmaydi);
# (3) FAIL-CLOSED: DB/pool/SQL xatosida allowed=False + reason=db_error va
#     ROLLBACK (yarim bron/yarim yechuv qolmaydi); mablag' yetishmasa ham
#     bazada IZ QOLMAYDI (SAVEPOINT);
# (4) refund_ai_request(user_id, reservation_id): ATOMIK va IDEMPOTENT —
#     manbaga qarab (kvota YOKI kredit) qaytaradi, 5 parallel refund'da ham
#     AYNAN 1 marta qaytadi;
# (5) Magic Post / AI Studio / Voice / Image / Post Score oqimlari AYNAN shu
#     transactional funksiyadan foydalanadi, hech birida fail-open qolmagan,
#     eski DB funksiyalari backward compatibility uchun saqlangan
#     (tests/atomic_quota_test.py).
"$PY" tests/atomic_quota_test.py || EXIT_CODE=1

echo
echo "===== 3p) PHASE 2 / 2-QADAM: TELEGRAM HTML SANITIZER + DELIVERY ====="
"$PY" tests/html_sanitizer_test.py || EXIT_CODE=1

echo
echo "===== 3q) 🔒 PHASE 2 / 3-QADAM: FSM TOZALASH VA MENYU XAVFSIZLIGI ====="
# (1) Oraliq holatlarda (MAGIC_INPUT, PHOTO_WAITING / IMAGE_POST_INPUT)
#     foydalanuvchi asosiy menyu yoki /start bossa, context.user_data tozalanib,
#     ConversationHandler.END qaytariladi va asosiy menyu ko'rsatiladi;
# (2) "❌ Bekor qilish" barcha oqimlarda yagona standartda ishlaydi:
#     sessiya tozalanadi, ConversationHandler.END bo'ladi;
# (3) Admin callbacklarida (adm_*) RBAC server-side from_user.id orqali qat'iy
#     tekshiriladi, non-admin show_alert=True bilan rad etiladi;
# (4) Middleware qatlami (FSMCleanerMiddleware, admin_rbac_required)
#     tizim yaxlitligini ta'minlaydi (tests/fsm_navigation_safety_test.py).
"$PY" tests/fsm_navigation_safety_test.py || EXIT_CODE=1

echo
echo "===== 3r) 🤖 PHASE 3: AI ENGINE VA SMM ORKESTRATSIYASI ====="
# (1) SMM Intent Router (8 ta intent: CREATE_POST, IMPROVE_POST, SHORTEN,
#     EXPAND, GENERATE_VARIANTS, POST_AUDIT, CONTENT_IDEAS, UNKNOWN);
# (2) Provider Fallback Chain (Gemini 2.5 Flash -> Groq -> OpenRouter -> Mock);
# (3) AIOutputValidator & Controlled Retry (bo'sh, yupqa va xavfli matnlarni
#     aniqlab, kuchaytirilgan prompt bilan AYNAN 1 marta qayta so'rov);
# (4) Phase 2 reserve_ai_request va fail-closed refund kafolati;
# (5) Telegram HTML Sanitization integratsiyasi (tests/ai_orchestrator_test.py).
"$PY" tests/ai_orchestrator_test.py || EXIT_CODE=1

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
