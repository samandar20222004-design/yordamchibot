# 📊 STATISTIKA + ⚙️ SOZLAMALAR + ⚙️ ADMIN PANEL — PostAssist V2 (5-MIKRO QADAM) hisoboti

**Sana:** 2026-09-14 · **Branch:** `arena/01a09e8f-yordamchibot` · **Testlar:** 7549 ✔ / 0 ✘

## 1) PR #109 — merge holati
PR #109 («📢 Kanallarim boshqaruv ekrani + 📅 Rejalashtirilgan bo'limi») **main'ga toza merge qilingan**
(merge commit `60c26a1`, mergedAt 2026-09-14T04:37:27Z). Lokal `main` va `origin/main` daraxtlari aynan bir xil
(`60c26a1…`), ishchi daraxt toza.

## 2) 📊 STATISTIKA (`handlers/analytics.py`)
- Bo'lim nomi aniq **«📊 Statistika»** (uz/ru/en) — uzun/noaniq nomlar yo'q.
- Oddiy foydalanuvchiga ixcham umumiy ekran: 📢 Ulangan kanallar • 📝 Yaratilgan postlar •
  📅 Rejalashtirilgan postlar • 🤖 AI so'rovlar / Sarflangan kreditlar.
- Natija ostida **[🔄 Yangilash] [◀️ Orqaga]**; Yangilash keshni tozalab qayta o'qiydi,
  Orqaga asosiy 6 tugmali menyuga qaytaradi.
- Kanal darajasidagi eski analitika (`an_ch:`/`an_other`) orqaga moslik uchun saqlandi;
  kanal yo'q bo'lsa ham ekran nollar bilan ochiladi.
- Yangi DB: `get_user_overview_stats()` (kanallar/postlar/reja + `credits_ledger` auditi
  asosida AI so'rovlar/kreditlar), `invalidate_user_overview_stats()`.

## 3) ⚙️ SOZLAMALAR (`handlers/settings.py` — yangi modul)
`[⚙️ Sozlamalar]` → profil kartasi + **yagona tartibli menyu** (inline `stgs_*`):

| | |
|---|---|
| 👤 Profil | 🌐 Til / Язык |
| 🔔 Bildirishnomalar | 🎨 Post sozlamalari |
| 💳 To'lovlar tarixi | 🎁 Do'stlarni taklif qilish |
| ❓ Yordam | ℹ️ Bot haqida |
| | ◀️ Orqaga | |

- ❓ Yordam va ℹ️ Bot haqida, 🎁 Do'stlarni taklif qilish shu menyu orqali ochiladi.
- Mavjud **Profil** (kabinet) va **Til almashtirish** oqimlari buzilmagan
  (`cab_*` callback'lari, `get_cabinet_inline_keyboard` va til klaviaturasi o'zgarmagan);
  eski kabinet tezkor tugmalari ham menyuda saqlanadi (orqaga moslik).
- 🔔 Bildirishnomalar va 🎨 Post sozlamalari — yangi `user_settings` jadvali
  (UPSERT, kalitlar OQ RO'YXAT bilan cheklangan — payload manipulyatsiyasi rad etiladi).
- 💳 To'lovlar tarixi — `payments` (Stars) + tasdiqlangan `payment_receipts` birlashgan
  (`get_user_payment_history()`), bo'sh holat ham chiroyli.

## 4) ⚙️ ADMIN PANEL (`handlers/admin.py`)
- Oddiy foydalanuvchiga **HECH QACHON** ko'rinmaydi: klaviaturada tugma yo'q (6 tugma
  standarti) + `admin_panel_menu`/`admin_dashboard_callback` server-side RBAC
  (`is_admin` + `verify_admin_callback`, fail-closed).
- Admin kirganda dashboard bilan birga **🩺 Tizim monitoringi** blogi chiqadi:
  🖥 Bot & DB (latency) • ⏰ Scheduler (jobs) • 🤖 AI provayderlar (Gemini/Groq/OpenRouter)
  • 💳 Pending manual to'lovlar. Health xato bo'lsa ham dashboard chiqadi (crash yo'q).
- Yangi `adm_health` callback — to'liq Health hisoboti (`format_health_report`),
  faqat `system_settings` RBAC ruxsati bilan; tampering himoyasi (`parse_callback_id`,
  payload'ga ishonilmaydi) saqlangan.

## 5) I18N va regression testlar
- Yangi `translations/settings_stats.py` — 48 kalit, **UZ/RU/EN 100% paritet**
  (`settings_stats_parity_report`: missing/extra/format/empty — hammasi bo'sh).
- Yangi `tests/settings_and_stats_v2_test.py` — **289 ta chek**:
  (1) statistika formati + [🔄/◀️] amallari; (2) 8 ta sub-tugma ochilishi + Orqaga;
  (3) Admin Panel RBAC (klaviatura, handlerlar, callback tampering, health ruxsati);
  (4) i18n paritet; (5) regressiya qo'riqonlari (6-tugma menyu, FSM, eski callback'lar).
- Runner: `tests/run_tests.sh` ga 3g-bosqich qo'shildi.
- Natija: `PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh` →
  **BARCHA TESTLAR 100% YASHIL**: mavjud 7260 ✔ saqlandi + 289 yangi ✔ = 7549 ✔ / 0 ✘.
