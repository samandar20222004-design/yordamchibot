# ⚙️ SOZLAMALAR MENYUSI + 🧰 VOSITALAR — PostAssist V2 · 3-QADAM hisoboti

**Sana:** 2026-09-14 · **Branch:** `arena/01a09f1d-yordamchibot` · **Testlar:** 8535 ✔ / 0 ✘ · **Lint gate (ruff+flake8):** toza

## 1) PR #113 — merge holati
PR #113 («PostAssist V2 · 2-qadam: B1 navbat + B2 yagona rasm oqimi + 7/30
kontent-reja») `main`'ga **toza merge qilingan**: merge commit
`a877fcf1aca962be3ca78bd5c05293bd5745caa7`, mergedAt `2026-09-14T08:51:18Z`.
Joriy branch aynan shu commit'dan olingan, ishchi daraxt toza
(`git status` → `nothing to commit, working tree clean`). Ya'ni 1-band
allaqachon bajarilgan — qo'shimcha merge talab qilinmadi.

## 2) ⚙️ SOZLAMALAR menyusidagi legacy dublikatlar tozalandi

**Muammo:** menyu `include_legacy=True` bilan chizilardi va speks qatorlaridan
keyin eski kabinet tezkor tugmalari (📢 Mening kanallarim, 📊 Analitika,
📅 Kutilayotgan postlar, 📅 Rejalashtirilgan, 💎 Ballar & reklama rejimi,
🎁 Kunlik bonus, 🗂 kabinet) **takroran** chiqardi — ular o'z asosiy
menyularida allaqachon bor edi.

**Yechim** (`keyboards/inline.py`, `handlers/settings.py`):
- `get_settings_hub_keyboard(lang, include_legacy=False)` — legacy blok
  **butunlay olib tashlandi**; `include_legacy` parametri orqaga moslik uchun
  imzoda qoldi, lekin qiymatidan qat'i nazar hech narsa chizmaydi
  (eski chaqiruv kod `TypeError` bilan yiqilmaydi).
- Menyu yagona, tartibli va **to'liq** ko'rinishga keltirildi — aynan speks
  tartibida **12 tugma + [◀️ Orqaga]**:

| | |
|---|---|
| 👤 Profil → `stgs_profile` | 🌐 Til / Язык → `stgs_lang` |
| 💎 Ballarim → `stgs_points` | 🔄 Ballar o'tkazish → `stgs_transfer` |
| 🎁 Kunlik bonus → `stgs_bonus` | 👥 Do'stlarni taklif → `stgs_referral` |
| 🔔 Bildirishnomalar → `stgs_notif` | 🎨 Post sozlamalari → `stgs_post` |
| 💳 To'lovlar tarixi → `stgs_pay` | 🧰 Vositalar → `stgs_tools` |
| ❓ Yordam → `stgs_help` | ℹ️ Bot haqida → `stgs_about` |
| | ◀️ Orqaga → `stgs_back` |

- **Eski `cab_*` callback'lari O'CHIRILMADI.** `handlers/start.cabinet_callback`
  (`^cab_|^close_cabinet`) o'z joyida — chat tarixidagi eski tugmalar xavfsiz
  alias/redirect sifatida ishlashda davom etadi (`cab_channels`, `cab_pending`,
  `cab_queue`, `cab_balance`, `cab_bonus`, `cab_referral`, `cab_lang*`,
  `cab_main`, `cab_converter`, `cab_guide`, `close_cabinet`).
- Yangi matnlar **asosiy lug'atdagi yagona manbadan** olinadi
  (`cab_btn_daily_bonus` → «🎁 Kunlik bonus», `cab_referral` →
  «👥 Do'stlarni taklif») — takroriy matn yaratilmagan.

## 3) 🧰 VOSITALAR submenyusi (`handlers/tools.py` — yangi modul)

Ilgari yashirinib qolgan **Konvertor (#38)** va **Post Enhancer (#9)** endi
o'zining aniq, ko'rinadigan mantiqiy joyida:

| Tugma | callback | Oqim |
|---|---|---|
| 🔤 Kirill-Lotin Konvertor | `extra_converter` | `handlers.converter.converter_inline_entry` → `CONVERT_INPUT` |
| ✨ Tugma & Reaksiyalar (Post Enhancer) | `extra_enhancer` | `handlers.post_enhancer.post_enhancer_start` → `ENH_POST` |
| ◀️ Orqaga | `stgs_hub` | ⚙️ Sozlamalar menyusi qayta chiziladi (yangi xabar yo'q) |

- **Yangi FSM yo'q, yangi prefiks yo'q** — ikkala tugma mavjud, sinovdan
  o'tgan oqimlarga ulanadi; eski «⚙️ Qo'shimcha funksiyalar» reply-tugmasi va
  `extra_close` callback'i ham o'zgarmagan.
- Submenyu matni `translations/settings_stats.py` (`ss_tools_title`,
  `ss_tools_btn_*`).

## 4) 🔄 Ballar o'tkazish menyudan ham ochiladi
- `handlers.start.transfer_inline_entry` — `stgs_transfer` callback'i uchun
  yagona kirish nuqtasi; `start_transfer_credits` (reply-tugma) bilan bitta
  yordamchi (`_begin_transfer_flow`) orqali ishlaydi: **matn, cheklovlar
  (≥3 ball), xato holatlari va `TRANSFER_TARGET → TRANSFER_AMOUNT` FSM bir xil**.
- Handler `start_handlers` ro'yxatiga qo'shildi → u ham `main_conv` entry
  point'i, ham **har bir faol holatda menyu sakrashi** (`all_menu_jumps`), ham
  global reyestr handleri. Suhbat faol bo'lgan chekka holatda ham foydalanuvchi
  jim qolmaydi (fail-safe toast: `sys_stale_button`).

## 5) I18N va testlar
- `translations/settings_stats.py` — yangi kalitlar (`ss_btn_points`,
  `ss_btn_transfer`, `ss_btn_tools`, `ss_tools_title`, `ss_tools_btn_converter`,
  `ss_tools_btn_enhancer`) UZ/RU/EN da 100% paritet:
  `settings_stats_parity_report()` → `in_sync: True`, **54 kalit**, missing/extra/
  format_mismatch/empty — hammasi bo'sh.
- Yangi `tests/refactor_step3_test.py` — **246 chek**:
  1. sozlamalar menyusida legacy dublikatlar yo'qligi va 12+1 tugma speks
     tartibida (uchala til), `include_legacy=True` ham legacy chizmasligi;
  2. Ballarim / Ballar o'tkazish / Kunlik bonus / Referral ochilishi
     (routing, FSM holati, DB amali, admin rejimi, kam ball holati);
  3. Vositalar ichida Konvertor va Post Enhancer ochilishi (klaviatura, matn,
     `CONVERT_INPUT` / `ENH_POST` holatlari, Orqaga → hub);
  4. eski `cab_*` callback'lari va legacy buyruqlar/tugmalar crash bermasligi;
  5. i18n paritet + callback xavfsizligi (64 bayt, tilga bog'liq emaslik).
- Mavjud guard-testlar yangi speksga moslashtirildi (coverage kamaymagan):
  `tests/settings_and_stats_v2_test.py` (289 → **303** chek, endi uchala tilda
  legacy yo'qligini ham tekshiradi), `telegram_bot/tests/new_requirements_test.py`
  (kabinet ekranida legacy dublikat **yo'q**ligi asserti).
- Runner: `tests/run_tests.sh` ga **3j** bosqichi qo'shildi.
- CI muhitidagi deps (`pytest`, `pgserver`, `sentry-sdk`) bilan to'liq runner ham
  yashil — bu holatda qo'shimcha ~528 test ishga tushadi (bazaviy o'lchov
  7745 `[OK]` bu depslarsiz olingan edi).
- **Lint gate** (`ruff==0.6.9` + `flake8==7.1.1`, `--select=E9,F63,F7,F82`) toza.
  Bu gate haqiqiy xatoni topdi: `handlers/settings.py` da
  `localize_db_message` import qilinmagan edi (kunlik bonus «allaqachon olingan»
  yo'li `NameError` berardi) — tuzatildi va shu yo'l uchun regressiya testi
  qo'shildi (`tests/refactor_step3_test.py`, 2g-2).
- Yakuniy natija: `PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh` →
  **8535 `[OK]` / 0 `[FAIL]`** (yangi 3-qadam to'plami — 246 chek, barcha mavjud
  testlar yashil), chiqish kodi `0`, «BARCHA TESTLAR 100% YASHIL ✔».
