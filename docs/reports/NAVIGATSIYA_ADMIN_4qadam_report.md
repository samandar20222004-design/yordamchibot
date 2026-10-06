# 🧭 NAVIGATSIYA STACKI + 👑 ADMIN DASHBOARD — PostAssist V2 · 4-QADAM hisoboti

**Sana:** 2026-09-14 · **Branch:** `arena/01a09f45-yordamchibot` · **Testlar:** 100% yashil
(`bash tests/run_tests.sh` → EXIT_CODE=0, **8243 ta [OK] tekshiruv, 0 xato** — bazadagi
8009 ta [OK] dan **+234**; shu jumladan yangi `tests/refactor_step4_test.py` dagi
**219 ta** kontrakt testi) · **Lint gate (ruff+flake8, E9/F63/F7/F82):** toza

## 1) PR #114 — merge holati
PR #114 («⚙️ PostAssist V2 · 3-qadam: Sozlamalar menyusi (legacy dublikatlarsiz) +
🧰 Vositalar hub'i») `main`'ga **toza merge qilingan**: holat `MERGED`, merge commit
`c4bd928148db60a24c9532a012c9abf726636c16`, mergedAt `2026-09-14T09:34:06Z`. Joriy
branch aynan shu commit'dan olingan (`git rev-parse main == HEAD == c4bd928`), ishchi
daraxt toza. Ya'ni 1-band bajarilgan — qo'shimcha merge talab qilinmadi.

## 2) 🧭 NAVIGATSIYA STACKI VA ◀️ Orqaga / ❌ Bekor qilish / 🏠 Asosiy menyu standarti

**Yangi modul** — `telegram_bot/handlers/navigation.py` (yagona manba):
- Bo'lim kalitlari: `SECTION_MAIN / CONTENT / AI_STUDIO / CHANNELS / SETTINGS /
  TOOLS / ADMIN` + `NAV_SECTIONS` konstantasi;
- `remember_section / current_section / clear_section` — foydalanuvchi qaysi
  bo'limda ekanini `user_data["nav_section"]` da eslab qoladi;
- `render_section_start_message(...)` — «bo'lim boshiga» qaytish ekranini chizadi
  (content / ai_studio / channels / settings / tools / admin); xatoda `False` —
  chaqiruvchi asosiy menyuga fallback qiladi (fail-safe);
- `clear_fsm_data` endi `nav_section`ni **omon saqlaydi** — FSM tozalanishiga
  qaramay cancel/oqim o'z bo'limini bilib turadi.

**Uchta nomlangan oqim** (har bir ichki ekran foydalanuvchi qayerdan kelganini biladi):

| Oqim | Amal | Fayl |
|---|---|---|
| Kontent → 🤖 AI Yordamchi → **[◀️ Orqaga]** → **Kontent yaratish submenyusi** (asosiy menyuga sakramaydi) | YANGI `ai_back_to_content` callback'i + AI Studio klaviaturasiga `[◀️ Orqaga]` tugmasi (`keyboards/inline.py`) | `handlers/ai_assistant.py` |
| Kanallarim → Kanal → **[◀️ Orqaga]** → **Kanallar ro'yxati** | mavjud `ch_back` (`channels_list_callback`) — regressiya testi bilan qo'riqlandi | `handlers/channels.py` |
| Sozlamalar → 🧰 Vositalar → **[◀️ Orqaga]** → **Sozlamalar menyusi** | mavjud `stgs_hub` — regressiya testi bilan qo'riqlandi | `handlers/settings.py` |

**Uch tugma mantig'i ajratildi** (AI Yordamchi bo'limi — namuna oqim):
- **Oddiy ko'rishda [◀️ Orqaga]** → parent menyu: ichki vosita ekranlarida
  `ai_back_to_menu` → AI Studio hub; hub'da YANGI `ai_back_to_content` → Kontent
  submenyusi;
- **FSM ichida [❌ Bekor qilish]** → kontekst tozalanadi va **o'sha bo'lim boshiga**
  qaytadi: `ai_close` / `ai_post_cancel` endi asosiy menyuga emas, **AI Studio
  hub'iga** qaytadi; `adm_cancel` (admin oqimlari) → admin dashboard; global
  `cancel_handler` endi `nav_section`ga qarab Kontent submenu / AI Studio hub /
  Kanallar ro'yxati / Sozlamalar / Vositalar ekranini qayta chizadi (bo'lim
  noma'lum bo'lsa — asosiy menyu, to'liq orqaga moslik);
- **[🏠 Asosiy menyu]** → istalgan joydan asosiy 6 tugmali menyu: YANGI
  `ai_exit_to_menu` handleri (`studio_close` callback'i o'zgarmagan — eski chat
  tarixidagi tugmalar ham ishlaydi).

Routing: `ai_back_to_content` barcha 14+ AI holatida va entry point sifatida
ro'yxatdan o'tdi; `studio_close` entry point pattern'ga qo'shildi (stale tugmalar
uchun); `SET_POST_TAG` / `AI_SETTINGS` holatlariga `adm_` callback handleri
qo'shildi (admin FSM ichida ⬅️ Orqaga/❌ Bekor qilish to'g'ri ishlaydi).

## 3) 👑 ADMIN PANEL DASHBOARD — yagona markaz (12 tugma + Yopish)

`get_admin_dashboard_keyboard` endi topshiriqdagi AYNAN layout (7 qator / 13 tugma):

| | |
|---|---|
| 📊 To'liq statistika → `adm_stats` | 📢 Ommaviy xabar → `adm_broadcast` |
| 🎯 Reklama markazi → `adm_adhub` | 📋 Kanallar ro'yxati → `adm_channels` |
| 📋 Barcha postlar → `adm_posts` **(yangi)** | 🎁 Promo-kod yaratish → `adm_promo` |
| ⭐️ PRO berish → `adm_grant_pro` | 🏷 Post nishoni → `adm_tag` **(yangi)** |
| ⚙️ AI parametrlari → `adm_ai` **(yangi)** | 🗄️ DB / Kesh holati → `adm_dbcache` **(yangi)** |
| 🩺 Tizim salomatligi → `adm_health` (endiko'rinadi) | 📜 Audit \| 👥 Rollar → `adm_audit_roles` **(yangi)** |
| | ❌ Yopish → `close_msg` |

- **Yangi callback'lar** (`handlers/admin.py` → `admin_dashboard_callback` ichida):
  * `adm_posts` — oxirgi 15 post (`db.get_recent_posts`), END;
  * `adm_tag` — Post nishoni yo'riqnomasi → `SET_POST_TAG` FSM (o'zgarish
    `post_tag_received`da OWNER ruxsati bilan fail-closed);
  * `adm_ai` — AI parametrlar ekrani → `AI_SETTINGS` FSM (o'zgarish
    `ai_settings_received`da OWNER ruxsati bilan fail-closed);
  * `adm_dbcache` — DB Pool/Kesh holati + `cache_clear` (OWNER fail-closed);
  * `adm_audit_roles` — `/audit` formatidagi jurnal + `list_admin_roles` rollari
    (faqat OWNER/SUPER_ADMIN — `/audit` bilan bir xil qoida).
- **Dublikat statistika handlerlari birlashtirildi**: `adm_stats` (callback),
  `/admin_stats` (buyruq) va «📊 Statistika» reply-tugmasi / `/stats`
  (`show_statistics`) endi UCHALASI yagona `_build_full_stats_text` ekranni
  chiqaradi. Xuddi shunday: `adm_posts` ≡ `admin_all_posts`,
  `adm_channels` ≡ `admin_all_channels` (bir xil builder'lar).
- **Eski admin reply-klaviaturasi to'liq integratsiya qilindi** (alias sifatida
  saqlandi): «🏷 Post nishoni», «⚙️ AI parametrlari», «🗄️ DB/Kesh», «📋 Barcha
  postlar», «📋 Barcha kanal/guruhlar», «📊 Statistika», «🎯 Reklama markazi»,
  «📢 Majburiy obuna», «➕ Homiy kanal qo'shish», «📢 Ommaviy xabar» — hammasi
  ishlayveradi va router testlari bilan qo'riqlandi (`tests/refactor_step4_test.py`,
  TEST 3e/3f).
- **Server-side RBAC va fail-closed saqlandi**: har bir `adm_*` callback
  `admin_dashboard_callback` BOSHIDA `is_admin` + `verify_admin_callback`
  (server-side `from_user.id`, payload'ga ishonilmaydi) tekshiruvidan o'tadi;
  ruxsatga bog'liq bo'limlar (`adm_promo` → manage_promos, `adm_grant_pro` /
  `adm_broadcast` → manage_users, `adm_health` → system_settings,
  `adm_audit_roles` → SUPER_ADMIN) o'z tekshiruvlarini saqlab qoldi.

## 4) 🧪 REGRESSIYA VA I18N TESTLARI — `tests/refactor_step4_test.py` (yangi, 219 ta)

* **TEST 1 — Navigatsiya stacki:** Kontent → AI → [◀️ Orqaga] → Kontent submenyusi
  (uchala til, asosiy menyuga sakramasligi aniqlangan); Kanallarim → Kanal →
  [◀️ Orqaga] → kanallar ro'yxati; Sozlamalar → Vositalar → [◀️ Orqaga] →
  Sozlamalar menyusi (13 tugma).
* **TEST 2 — FSM ichida Bekor qilish:** `ai_close` → kontekst tozalanadi + AI Studio
  hub (bo'lim boshi); `cancel_handler` → Kontent/AI bo'lim boshiga qaytadi, legacy
  holatda asosiy menyu; `adm_cancel` → dashboard + `admin_flow` tozalanadi;
  `clear_fsm_data` nav_section'ni saqlaydi; [🏠 Asosiy menyu] alohida (ai_exit_to_menu).
* **TEST 3 — Admin dashboard yagona markaz:** 13 tugma AYNAN speks tartibida;
  yangi 5 callback adminga ochiladi va to'g'ri holat/ekran qaytaradi; statistika
  uch yo'lidayn bir xil ekran; eski reply-tugmalar real router orqali alias
  sifatida ishlaydi.
* **TEST 4 — Tampering (fail-closed):** 19 ta `adm_*` callback'ning BARCHASI oddiy
  foydalanuvchi uchun qat'iy yopiq — `verify_admin_callback → False`, rad javobi
  («Ruxsat yo'q»), hech qanday ekran chizilmaydi, **hech qanday DB amali
  bajarilmaydi**; soxtalashtirilgan payload (`adm_grant_pro:777` ...) ham
  server-side from_user.id tufayli baribir rad etiladi; Admin Panel tugmasi oddiy
  foydalanuvchiga ko'rinmaydi.
* **TEST 5 — I18N + callback xavfsizligi:** `content_menu` UZ/RU/EN 100% paritet
  (`in_sync: True`, [◀️ Orqaga] yorlig'i submenu bilan AYNAN bir xil); AI Studio
  callback'lari tilga bog'liq emas; barcha yangi callback'lar Telegram 64-bayt
  chegarasida; `render_section_start_message` har bir bo'lim boshini chizadi.

**Runner:** `tests/run_tests.sh` ga `3k` bosqichi qo'shildi. Eski speksni qo'riqlagan
3 ta kompozitsiya invarianti yangi speksga yangilandi (unit_test: studio kb 6→7,
dashboard 6→12; refactor_step2: hub 6→7 — 4-qadam ataylab kiritgan o'zgarishi).

## 5) Tekshiruv natijalari
```
PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh
→ BARCHA TESTLAR 100% YASHIL ✔ (EXIT_CODE=0)
→ 8243 [OK] / 0 [FAIL]  (baza: 8009 [OK] → +234)
→ ruff check . --select=E9,F63,F7,F82  → All checks passed!
→ flake8 . --select=E9,F63,F7,F82     → 0
```
