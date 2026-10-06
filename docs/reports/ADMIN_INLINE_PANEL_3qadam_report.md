# ⛔️ ADMIN REPLY-KLAVIATURA OLIB TASHLANDI + 👑 YAGONA INLINE PANEL — 3-BOSQICH hisoboti

**Sana:** 2026-09-14 · **Branch:** `arena/01a0a0d0-yordamchibot` (base: `main` @ `d66ce04`) ·
**Testlar:** 100% yashil (`PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh` → `EXIT_CODE=0`,
**9052 ta [OK] / 0 [FAIL]** — oldin **8898 [OK]**; ya'ni **+154** yangi tekshiruv) ·
**Lint gate** (`ruff==0.6.9` + `flake8==7.1.1`, `--select=E9,F63,F7,F82`): toza.

---

## 1) PR #119 — merge holati

PR **#119** («feat(settings): complete PR #118 8-group settings hub») `main`'ga **toza merge
qilingan**: `state = MERGED`, `mergeCommit = d66ce04f3a3885df29383cc6d3376aea12004df5`,
`mergedAt = 2026-09-14T16:42:22Z`.

```
git rev-parse main == origin/main == HEAD == d66ce04f3a3885df29383cc6d3376aea12004df5
git status  → "nothing to commit, working tree clean"
```

Joriy ish branch aynan shu merge-commit'dan olingan, ya'ni 1-band **bajarilgan** — qo'shimcha
merge/qayta merge talab qilinmadi (toza holat tasdiqlandi).

---

## 2) ⛔️ Admin panel reply-klaviaturasi BUTUNLAY olib tashlandi

Ilgari admin panel ochilganda pastda oq (reply) 10 talik klaviatura chizilardi:

```
[📢 Majburiy obuna]        [📊 To'liq statistika]
[🎯 Reklama markazi]       [🏷 Post nishoni]
[⚙️ AI parametrlar]        [🗄️ DB / Kesh holati]
[✉️ Xabar yuborish]        [📋 Barcha postlar]
[📋 Barcha kanal/guruhlar] [🔙 Asosiy menyu]
```

Endi bu klaviatura **hech qachon chizilmaydi**. Amalga oshirilgan o'zgarishlar:

| Joy | O'zgarish |
|---|---|
| `keyboards/default.py` | `get_admin_panel_keyboard()` endi **har doim `ReplyKeyboardRemove()`** qaytaradi (API nomi moslik uchun qoldi — eski chaqiruv ham yangi tugma chizib qo'ya olmaydi, defense-in-depth). Foydalanilmagan `get_sponsors_keyboard()` (reply) butunlay o'chirildi. Eski yorliqlar `ADMIN_LEGACY_REPLY_ROWS` / `ADMIN_LEGACY_REPLY_TEXTS` registrida **hujjat + test** uchun saqlandi. |
| `keyboards/reply.py` | Fasad ham `ADMIN_LEGACY_REPLY_*` va deprecated `get_admin_panel_keyboard` ni qayta eksport qiladi (import mosligi). |
| `handlers/admin.py` | **Barcha** `reply_markup=get_admin_panel_keyboard()` chaqiruvlari (20 ta joy) inline panelga (`get_admin_dashboard_keyboard()`) almashtirildi; matn kutuvchi FSM ekranlaridagi reply `get_cancel_keyboard()` (11 ta joy) esa inline `get_admin_back_keyboard()` (⬅️ Orqaga / ❌ Bekor qilish → `adm_back` / `adm_cancel`) qilindi. Reply klaviatura chizadigan importlar olib tashlandi. |
| Reply klaviatura o'rni | **Asosiy menyu saqlanadi** (admin oqimi endi hech qanday reply klaviaturani qayta chizmaydi). ❌ Yopish (`close_msg`), ⬅️ Orqaga (`adm_back`), ❌ Bekor qilish (`adm_cancel`) — barchasi inline. |

**Eski reply matnlari — FAQAT orqa fonda ALIAS** (`handlers/__init__.py` routing'i
o'zgarmadi): `📢 Majburiy obuna`, `📊 To'liq statistika`, `🎯 Reklama markazi`,
`🏷 Post nishoni`, `⚙️ AI parametrlar`, `🗄️ DB / Kesh holati`, `✉️ Xabar yuborish`,
`📋 Barcha postlar`, `📋 Barcha kanal/guruhlar`, `⚙️ Admin Panel` (+ UZ/RU/EN
aliaslari). Chat tarixidan yozilsa yoki eski xabardagi tugma bosilsa — handler ishlaydi;
lekin ular **hech qanday klaviaturada ko'rinmaydi**.

---

## 3) 👑 Yagona INLINE panel — layout SSOT

`keyboards/inline.py::ADMIN_DASHBOARD_ROWS` — yagona manba; klaviatura ham, testlar ham,
hujjat ham shundan o'qiydi. Layout topshiriq bo'yicha **AYNAN** (6 qator × 2 = 12 tugma):

| | |
|---|---|
| 📊 Bot statistikasi | 📢 Ommaviy xabar |
| 🎯 Reklama markazi | 📋 Kanallar ro'yxati |
| 📋 Barcha postlar | 🎁 Promo-kod yaratish |
| ⭐️ PRO berish | 🏷 Post nishoni |
| ⚙️ AI parametrlari | 🗄️ DB / Kesh holati |
| 🩺 Tizim monitoringi | ❌ Yopish |

Callback'lar o'zgarmadi (`adm_stats`, `adm_broadcast`, `adm_adhub`, `adm_channels`,
`adm_posts`, `adm_promo`, `adm_grant_pro`, `adm_tag`, `adm_ai`, `adm_dbcache`,
`adm_health`, `close_msg`) — barchasi server-side RBAC (`is_admin` + `verify_admin_callback`,
fail-closed) bilan ishlaydi.

**Funksiya yo'qolmadi:** «📜 Audit | 👥 Rollar» (`adm_audit_roles`) dashboard'dan
**🩺 Tizim monitoringi** ekraniga ko'chirildi — yangi
`get_admin_monitoring_keyboard()` = `[📜 Audit | 👥 Rollar]` + `[⬅️ Orqaga] [❌ Yopish]`.
OWNER/SUPER_ADMIN tekshiruvi o'z joyida qoldi.

---

## 4) 🧪 Regression va testlar

Yangilangan/qo'shilgan tekshiruvlar:

| Fayl | Nima tekshiriladi | Natija |
|---|---|---|
| `tests/refactor_step4_test.py` | **TEST 3** — yangi layout (6×2, SSOT bilan aynan), monitoring ekranida audit; **TEST 3b (YANGI)** — `ReplyKeyboardRemove`, manba-darajasida reply chaqiruvlar yo'q, **13 ta legacy admin handler**ning HAQIQIY chaqiruvida reply-klaviatura chizilmasligi + ekran INLINE bo'lishi, RBAC; **TEST 4** — barcha `adm_*` non-admin uchun yopiq | 220 → **279** ✔ |
| `tests/final_acceptance_suite_test.py` | **TEST AG (YANGI)** — reply klaviatura qaytmasligi, layout AYNAN 12 tugma, **11 ta `adm_*` + navigatsiya callback'i** admin uchun ishlaydi (holat/ekran), eski matnlar router ALIAS'i sifatida ishlaydi, oddiy foydalanuvchiga panel 100% yopiq | 491 → **566** ✔ |
| `tests/statistics_isolation_test.py` | T5 — admin statistikasi endi inline panel tugmasi («📊 Bot statistikasi»); eski «📊 To'liq statistika» yorlig'i panelda yo'q, alias sifatida `/stats` orqali ishlaydi; ekran INLINE klaviatura bilan chiziladi | 190 → **197** ✔ |
| `telegram_bot/tests/unit_test.py` | `test_admin_new_buttons`, `test_ad_hub_unification_suite`, `test_admin_dashboard_layout_suite` — reply-klaviatura o'rniga ReplyKeyboardRemove + yangi inline layout | 344 ✔ |

To'liq runner: **barcha 17 bosqich `xato=0`**, `BARCHA TESTLAR 100% YASHIL ✔`, `EXIT_CODE=0`.
Jami: **9052 [OK] / 0 [FAIL]** (oldin 8898 [OK]).

---

## 5) 🛡 Xavfsizlik (RBAC fail-closed) — saqlanib qoldi

* `admin_panel_menu` va barcha admin handlerlar `is_admin(...)` tekshiruvidan o'tmagan
  update'ni **jim rad** etadi (ekran chizilmaydi, DB amali bo'lmaydi);
* har bir `adm_*` callback `verify_admin_callback(...)` orqali **server-side**
  (`from_user.id`, payload emas) tekshiriladi; oddiy foydalanuvchi uchun `show_alert` rad
  javobi va **hech qanday ekran**;
* `adm_audit_roles` — OWNER/SUPER_ADMIN, `adm_health` — `system_settings`,
  `adm_promo` — `manage_promos`, `adm_grant_pro`/`adm_broadcast` — `manage_users`
  (avvalgidek);
* oddiy foydalanuvchi asosiy menyusida `⚙️ Admin Panel` va eski admin tugmalari
  **umuman ko'rinmaydi** (uchala til, admin/user variantlari test bilan qo'riqlanadi).

---

## 6) 📦 O'zgargan fayllar

```
telegram_bot/keyboards/default.py     | reply klaviatura → ReplyKeyboardRemove + legacy registr
telegram_bot/keyboards/inline.py      | ADMIN_DASHBOARD_ROWS (12 tugma) + monitoring klaviaturasi
telegram_bot/keyboards/reply.py       | fasad eksportlari (legacy registr, deprecated funksiya)
telegram_bot/handlers/admin.py        | 20 reply chaqiruv → inline panel; 11 reply cancel → inline
telegram_bot/tests/unit_test.py       | 3 suite yangilandi (yangi kontrakt)
tests/refactor_step4_test.py          | TEST 3 yangilandi + TEST 3b (reply-klaviatura qo'riqoni)
tests/final_acceptance_suite_test.py  | TEST AG (33-test to'plami)
tests/statistics_isolation_test.py    | T5 yangilandi
tests/run_tests.sh                    | bosqich izohlari (3k / 3l) yangilandi
```
