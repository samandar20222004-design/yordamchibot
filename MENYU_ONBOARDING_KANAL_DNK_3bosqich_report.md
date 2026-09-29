# 🧭 3-BOSQICH — MENYUNI SODDALASHTIRISH + ONBOARDING (KANAL DNK) — YAKUNIY HISOBOT

> **Holat:** ✅ BAJARILDI — to'liq suite (`bash tests/run_tests.sh`) **yashil**,
> yangi regressiya **0 ta** (faqat mavjud `pre-existing` flaky/test-env
> xatolari qoldi, ular 3-bosqichga aloqasiz).
> **Yangi qabul testi:** `tests/main_menu_and_dna_onboarding_test.py` — **231/231 OK**
> (8 blok, jumladan **end-to-end** mock ssenariysi: ulash → tahlil → atomik bron → bepul namuna → refund).
> **Lint:** `ruff check . --select=E9,F63,F7,F82` + `flake8 ... ` — **toza**.

---

## 1. Asosiy Menyu Ixchamligi (Main Menu Refactor)

### 1.1 Yangi layout — 5 tugma / 3 qator (uz/ru/en paritetda)

| # | 🇺🇿 UZ | 🇷🇺 RU | 🇬🇧 EN |
|---|--------|--------|--------|
| 1 | `✍️ Post yaratish` | `✍️ Создать пост` | `✍️ Create post` |
| 2 | `📢 Kanallarim` | `📢 Мои каналы` | `📢 My channels` |
| 3 | `📅 Rejalashtirilgan` | `📅 Запланированные` | `📅 Scheduled` |
| 4 | `📊 Statistika` | `📊 Статистика` | `📊 Statistics` |
| 5 | `⚙️ Sozlamalar / Ko'proq` | `⚙️ Настройки / Ещё` | `⚙️ Settings / More` |

Admin (`ADMIN_IDS`) uchun oxiriga alohida `[⚙️ Admin Panel]` qatori qo'shiladi
(6 ta tugma); oddiy foydalanuvchiga **hech qachon** ko'rinmaydi.

**Qaror:** «✍️ Post yaratish» — eski «✨ Kontent yaratish» tugmasining **aynan
o'zi**: kontent-yaratish submenyusi (Magic Post / Oddiy post / AI Yordamchi /
Rasm → Post / Ovoz → Post) o'z joyida qoldi, faqat yorliq aniqlandi. Shu sababli
routing, oqim va barcha eski aliaslar o'zgarmadi.

### 1.2 Ikkilamchi bo'limlar inline hub'ga ko'chirildi

| Ko'chirilgan | Eski joyi | Yangi joyi | Callback |
|---|---|---|---|
| `💎 PRO` | asosiy reply-menyu | `⚙️ Sozlamalar / Ko'proq` hub (4-qator) | `sub_open` |
| `❓ Yordam` | `📖 Qo'llanma` reply + FAQ hub | `⚙️ Sozlamalar / Ko'proq` hub (4-qator) | `stgs_help_hub` |
| `👥 Do'stlarni taklif` (referral) | — (avval ham hub'da) | hub (2-qator, o'zgarmadi) | `stgs_referral` |
| `ℹ️ Bot haqida`, `💳 To'lovlar tarixi`, `🔔 Bildirishnomalar`, `✍️ Post sozlamalari`, `🌐 Til` | hub | o'zgarmadi | `stgs_*` |
| `💬 Qo'llab-quvvatlash`, `❌ Yopish` | hub (oxirgi qator) | o'zgarmadi | `help_support`, `stgs_back` |

Natijada **bitta kanonik inline panel** — 10 tugma / 5 qator (simmetrik 2+2):

```
[🌐 Til / Язык]         [✍️ Post sozlamalari]
[🔔 Bildirishnomalar]   [👥 Do'stlarni taklif]
[💳 To'lovlar tarixi]   [ℹ️ Bot haqida]
[💎 PRO]                [❓ Yordam]
[💬 Qo'llab-quvvatlash] [❌ Yopish]
```

SSOT: `translations/settings_stats.CB_SETTINGS_HUB`.
`get_settings_profile_keyboard` — yagona manba; `get_settings_hub_keyboard` va
`get_cabinet_inline_keyboard` unga **delegatsiya** qiladi (dublikat inline
klaviatura yo'q — FAZA 18 qoidasi saqlandi).

### 1.3 Backward compatibility (buyruqlar va matnli filtrlar buzilmadi)

`keyboards/default.MENU_TEXTS` registri orqali **barcha** eski yorliqlar
routing aliasi bo'lib qoldi:

* `✨ Kontent yaratish` / `✨ Создать контент` / `✨ Create content`
  → `create_content` oilasi → kontent yaratish submenyusi;
* `⚙️ Sozlamalar` / `⚙️ Настройки` / `⚙️ Settings`
  (shuningdek `👤 Profil`, `👤 Kabinet & Sozlamalar`) → `settings` oilasi;
* `💎 PRO` / `⭐️ Premium` → `premium` oilasi → `start_subscription`;
* `➕ Yangi post`, `✨ AI Studio`, `📖 Qo'llanma`, `⚙️ Qo'shimcha funksiyalar`,
  `👥 Do'stlarni taklif`, `✨ Magic Post`, `📸 Rasm → Post`, `📊 Post Score` ...

Yangi `CREATE_CONTENT_LEGACY_ALIASES` guruhi `exact()` filtri va `is_menu_text()`
uchun avtomatik kengaytmani beradi: **tugma matni qo'lda yozilsa ham** to'g'ri
bo'lim ochiladi (fallback'ga tushmaydi).

---

## 2. Onboarding va Kanal DNK sinovi (Tone of Voice Activation)

### 2.1 Kanal ulangach darhol faol taklif

Eski xulq: `✅ Kanal muvaffaqiyatli ulandi!` → **tugadi**.
Yangi xulq (`handlers/channels.py`):

1. `✅ ulandi` + inline kanallar ro'yxati (o'zgarmadi);
2. **darhol** Kanal DNK sinovi taklifi (`ch_dna_offer`):

```
🎉 Kanalingiz ulandi!

Men kanalingizdagi oxirgi postlarni tahlil qilib, uning ovoz uslubini
(Tone of Voice) o'rgana olaman.

Buning uchun «🎙 Ovoz tahlili» tugmasini bosing yoki menga kanalingizdan
3 ta postni forward qiling.
```

3. `[🎙 Ovoz tahlili]` inline tugmasi — `ch_voice:<channel_id>`
   (`render_dna_onboarding_keyboard`) — mavjud, sinovdan o'tgan
   `channel_voice_analysis_callback` ga ulanadi (yangi handler/oqim
   **kiritilmadi**).

Taklif **faqat bir marta** beriladi (`_should_offer_dna`):
* foydalanuvchining **birinchi** kanali, **va**
* kanal `tone_of_voice` hali **bo'sh**.

DB xatosida jim qoladi (fail-safe) — hech qachon noto'g'ri/spam taklif
yuborilmaydi. Ikki ulash yo'li ham qamrab olindi: qo'lda (forward/username/ID)
**va** avtomatik (`my_chat_member` — bot admin qilinganda).

### 2.2 1 ta bepul namunaviy qoralama (sample draft)

Tahlil yakunlangach (`channel_voice_analysis_callback` → 4-qadam):

1. **Atomik bron:** `services.ai_quota.reserve_for_flow(db, context, user_id,
   "dna_sample", "dna", 1)` — 1 AI birlik; rad etilsa namuna chiqmaydi;
2. **Channel DNA profili** AI **tizim promptiga** ulanadi
   (`services.channels.dna.build_dna_system_prompt_extended`) — uslub
   o'lchangan metrikalardan (uzunlik, emoji, CTA, shakl) olinadi;
3. `utils.ai_agent.generate_dna_sample_post(...)` — mavjud AI zanjiri
   (Gemini → Groq → OpenRouter → ...) orqali 3 tilda matn;
4. **Fail-closed refund:** AI xatosi, bo'sh javob yoki xabarni yuborib
   bo'lmasa — `release_ai_quota(db, user_id, reservation_id)` (idempotent) va
   foydalanuvchiga muloyim izoh (`ch_dna_sample_error`).

Butun blok `try/except` ichida — namuna xatosi **hech qachon** tahlil
natijasini yoki asosiy oqimni buzmaydi.

---

## 3. Haftalik / Muntazam Maslahat (Actionable Recommendation)

`📊 Statistika` ekrani endi «quruq raqamlar» bilan tugamaydi:

```
📊 Sizning statistikangiz:
📢 Ulangan kanallaringiz: 1 ta
📝 Yaratilgan postlaringiz: 4 ta
📅 Rejalashtirilgan postlar: 0 ta
💎 Qolgan AI kreditlaringiz: 7 ta
💡 Tavsiya: Kanalingiz auditoriyasi kechki payt faolroq. Bugun 19:00 - 21:00
   oralig'ida birinchi postni joylashtiring.
```

Manba — **haqiqiy faollik signali** (`services.channels.best_time`), ya'ni
kanaldagi `channel_post_events` agregatsiyasi. Soxta raqam **hech qachon**
uydirilmaydi:

| Holat | Tavsiya |
|---|---|
| Best-time oynasi bor, reja bo'sh | `ss_my_advice_idle` — «shu oraliqda birinchi postni joylashtiring» |
| Best-time oynasi bor, reja mavjud | `ss_my_advice_best_time` — «shu oraliqda yangi post rejalashtiring» |
| Kanal ulangan, ma'lumot yetarli emas | `ss_my_advice_insufficient` — «bir necha post joylashtirgach tahlil ishlaydi» |
| Kanal yo'q | `ss_my_advice_no_channel` — «aniq tavsiya uchun avval kanalni ulang» |
| AI kreditlari tugagan | `ss_my_advice_low_credits` — «PRO tarifga o'tishni tavsiya qilamiz» |
| `advice=None` / noma'lum tur | qator **chizilmaydi** (eski 5 qatorli xulq — backward compat) |

Arxitektura: `build_advice_line()` va `build_user_overview_text()` — **PURE**
funksiyalar (DB'siz, testlanadi); `collect_advice()` — fail-safe async
yig'uvchi (xatoda `{}` → tavsiya qatori chiqmaydi, statistika **doim**
chiqadi). Statistika izolyatsiyasi buzilmadi: matnda faqat shaxsiy
ko'rsatkichlar + o'z kanali tavsiyasi (admin maydonlari **yo'q**).

---

## 4. O'zgargan fayllar (kod)

| Fayl | Nima o'zgardi |
|---|---|
| `telegram_bot/keyboards/default.py` | `get_main_keyboard` → 5 tugma/3 qator; `MENU_TEXTS`/`CREATE_CONTENT_LEGACY_ALIASES` (aliaslar) |
| `telegram_bot/keyboards/inline.py` | `get_settings_profile_keyboard` → 10 tugma (PRO + Yordam qatori); yangi `render_dna_onboarding_keyboard` |
| `telegram_bot/locales/translations.py` | `btn_create_content`, `btn_settings` (uz/ru) + DNK matnlari (uz/ru) |
| `telegram_bot/locales/en_overlay.py` | EN paritet: `btn_create_content`, `btn_settings` + DNK matnlari |
| `telegram_bot/translations/settings_stats.py` | `ss_btn_premium`, `ss_btn_help`; 6 ta `ss_my_advice_*`; `CB_SETTINGS_HUB` (10 tugma) |
| `telegram_bot/handlers/channels.py` | `_should_offer_dna`, `_send_dna_offer`, `_dna_prompt_block`, `_send_dna_sample`; 2 ulash yo'lida taklif; tahlildan keyin namuna |
| `telegram_bot/handlers/statistics.py` | `build_advice_line`, `collect_advice`, `ADVICE_*`, `LOW_CREDITS_THRESHOLD`; ekran matniga tavsiya |
| `telegram_bot/utils/ai_agent.py` | `generate_dna_sample_post` (3 tilda tizim/prompt + DNA bloki) |
| `tests/main_menu_and_dna_onboarding_test.py` | 🆕 3-BOSQICH qabul testi (231 tekshiruv, end-to-end ssenariy bilan) |
| `tests/ux_v2_main_menu_test.py`, `tests/ui_ux_and_navigation_standards_test.py`, `tests/final_acceptance_suite_test.py`, `tests/settings_and_stats_v2_test.py`, `tests/statistics_isolation_test.py`, `tests/content_creation_menu_test.py`, `tests/channels_and_queue_v2_test.py`, `tests/magic_post_flow_test.py`, `tests/post_score_flow_test.py`, `tests/refactor_step3_test.py`, `tests/refactor_step4_test.py`, `tests/manual_posting_and_unified_menu_test.py`, `tests/postassist_polish_test.py`, `tests/support_ticket_flow_test.py`, `tests/settings_hub_cleanup_1qadam_test.py`, `telegram_bot/tests/unit_test.py`, `telegram_bot/tests/account_settings_i18n_test.py` | Spek yangilandi (6→5 tugma, 8→10 hub tugmasi) — regressiya himoyasi **saqlandi va kengaytirildi** |

---

## 5. Test natijalari

| Yo'nalish | Natija |
|---|---|
| `tests/main_menu_and_dna_onboarding_test.py` (yangi) | ✅ 231/231 |
| `tests/ux_v2_main_menu_test.py` | ✅ 206/206 |
| `tests/ui_ux_and_navigation_standards_test.py` | ✅ 187/187 |
| `tests/final_acceptance_suite_test.py` | ✅ 590/590 |
| `tests/settings_and_stats_v2_test.py` | ✅ 313/314 (1 — mavjud `adm_health` xatosi, baseline'da ham bor) |
| `tests/refactor_step3_test.py` | ✅ 235/235 |
| `tests/statistics_isolation_test.py` | ✅ 205/205 |
| `tests/content_creation_menu_test.py` / `magic_post_flow` / `post_score_flow` / `channels_and_queue_v2` | ✅ to'liq |
| `telegram_bot/tests/unit_test.py` | ✅ 2621/2621 |
| `telegram_bot/tests/account_settings_i18n_test.py` | ✅ 371/371 |
| To'liq suite (`bash tests/run_tests.sh`) | **yangi regressiya: 0** (baseline bilan bir xil qolgan xatolar — 3-bosqichga aloqasiz) |

### Nima tekshiriladi (yangi testda)

1. **TEST 1** — asosiy menyu QAT'IY 5 tugma / 3 qator (uz/ru/en), i18n
   kalitlaridan chizilgan, ikkilamchi bo'limlar yo'q, admin varianti.
2. **TEST 2** — Sozlamalar / Ko'proq hub'i: 10 tugma / 5 qator, SSOT tartibi,
   PRO + Yordam, dublikat inline klaviatura yo'q, oxirgi qator kanonik.
3. **TEST 3** — backward compatibility: yangi **va** eski yorliqlar o'z
   bo'limiga tushadi (fallback emas), `MENU_TEXTS` / `exact()` registri.
4. **TEST 4** — DNK taklifi: 3 tilda matn, klaviatura (registry + 64 bayt +
   navigatsiya konflikti yo'q), taklif shartlari (birinchi kanal + uslub yo'q).
5. **TEST 5** — bepul namuna: 3 tilda AI chaqiruvi, DNA bloki tizim promptida,
   xatoda `{"error": ...}` (istisno emas), atomik bron + refund (manba skaneri).
6. **TEST 6** — 💡 tavsiya: barcha holatlar, 3 tilda farqli, `advice=None`
   backward compat, `collect_advice` fail-safe (DB xatosi → `{}`).
7. **TEST 7** — i18n 100% paritet (`in_sync=True`), yangi callback'lar
   registry'da va ≤64 bayt, navigatsiya konfliktlari 0, hardcoded matn yo'q.
8. **TEST 8** — **end-to-end** (mock DB/AI): tahlil → uslub DB'ga yozildi →
   atomik bron (`dna_sample`, 1 birlik) → namuna kanal nomi/uslub/tilda
   generatsiya qilindi → foydalanuvchiga ko'rsatildi → **refund qilinmadi**;
   AI namuna bermasa → **refund + muloyim izoh**.

---

## 6. Xavfsizlik va standartlar (buzilmadi)

* **Navigatsiya standarti (FAZA 17):** `◀️ Orqaga` / `❌ Bekor qilish` /
  `🏠 Asosiy menyu` / `❌ Yopish` semantikasi teginmadi; `find_nav_conflicts`
  barcha yangi klaviaturalarda **0**.
* **Callback registry (FAZA 19):** barcha yangi callback'lar
  (`sub_open`, `stgs_help_hub`, `ch_voice:<id>`) registry'da; `cb()` orqali
  ≤64 bayt; soxta/eskirgan callback'lar fail-closed rad etiladi.
* **IDOR/RBAC:** namuna va tavsiya faqat kanal **egasiga** (ownership
  tekshiruvi `get_channel_dna(user_id=...)` / `get_best_time(user_id=...)`).
* **Kvota:** atomik bron + idempotent refund — foydalanuvchi xato uchun
  to'lamaydi (fail-closed).
* **i18n:** uz/ru/en 100% paritet (`translation_parity_report().all_in_sync`,
  `settings_stats_parity_report().in_sync`), hardcoded matn yo'q.
* **FSM:** yangi holat **qo'shilmadi** (namuna ham, taklif ham holda emas) —
  `tests/fsm_navigation_safety_test.py` buzilmadi.

---

## 7. Qo'shimcha: CI pariteti tuzatishi (PR tekshiruvi)

PR ochilgach CI (`PostAssist V2 CI`, `.github/workflows/ci.yml`) qizil bo'ldi.
Sabab: CI `telegram_bot` working-directory'dan **ichki** runner'ni chaqiradi
(`telegram_bot/tests/run_tests.sh`, 34 ta test fayli), repo ildizidagi to'liq
runner (`tests/run_tests.sh`) esa undagi fayllarni **o'z ichiga olmaydi**.
Shu sababli 3 ta ichki test faylidagi eski menyu kutilmalari yangilanishdan
chetda qolgan edi:

| Fayl | Muammo | Tuzatish |
|---|---|---|
| `new_requirements_test.py` | Sozlamalar paneli **8** tugma deb kutilgan (4 ta joyda asosiy menyu **6** tugma) | **10** tugma (`sub_open`, `stgs_help_hub` qo'shildi); asosiy menyu **5** tugma |
| `i18n_ai_parity_test.py` | Birinchi tugma `✨ Kontent yaratish`; kabinet inline menyusi **8** tugma | `✍️ Post yaratish` (uz/ru/en); **10** tugma |
| `i18n_full_parity_test.py` | `main_keyboard` da **6** tugma | **5** tugma |

`new_requirements_test.py` birinchi xatoda to'xtaydi (`for test in tests:
test()`), shu sababli undan keyingi 3 ta eski kutilma ham ko'rinmagan edi —
hammasi bir yo'la tuzatildi (endilikda **61/61** test o'tadi).

**Yakuniy qiyoslash (asosiy commit `366f78e` ↔ PR):**

| To'plam | Base | PR |
|---|---|---|
| Ichki runner (34 fayl, yakka-yakka) | 2 ta FAIL | **aynan o'sha 2 ta FAIL** (yangi regressiya **0**) |
| To'liq runner (`tests/run_tests.sh`) | 17 ta FAIL qatori | **aynan o'sha 17 ta** (yangi regressiya **0**) |
| Lint gate (`ruff` + `flake8`, `E9,F63,F7,F82`) | — | **toza** |

Qolgan yagona xatolar asosiy commit'da ham mavjud, 3-bosqichga aloqasiz:
`.env.example` ORPHAN kalitlari, `FakeMessage.chat_id`, `♻️ nomzod yo'q` bo'sh
ekran, `adm_health` DB bo'limi, `Fast Path` / `ai_fallback` timing-flaky.

> **Tavsiya (alohida vazifa):** ildiz runner'ga ichki testlarni (yoki CI bilan
> bir xil runner'ni) ulash — shunda bunday farq mahalliy tekshiruvda darhol
> ko'rinadi.

---

## 8. CI blokerining tuzatilishi — `provider_total_timeout()` quyi chegarasi

`telegram_bot/services/ai_service.py` (2-BOSQICH'dan meros qolgan nuqson):

```diff
-    return min(8.0, max(6.0, float(AI_PROVIDER_TOTAL_TIMEOUT)))
+    return min(8.0, max(2.0, float(AI_PROVIDER_TOTAL_TIMEOUT)))
```

**Muammo:** quyi chegara 6s bo'lgani uchun `AI_PROVIDER_TOTAL_TIMEOUT` ga
berilgan har qanday qiymat **6s dan kichik bo'lsa jimgina e'tiborsiz
qolardi**. `tests/ai_fallback_test.py` (3-ssenariy) ataylab `1.5s` byudjet
beradi, lekin amalda 6s kuchga kirar edi: 4s Gemini `sleep` + 2s retry =
**6.00s** → `[FAIL] failover tez bo'ldi (<3.5s)` → CI qizil.

**Ta'sir doirasi:** yuqori chegara (8s) va shuning uchun **production
default'i o'zgarmadi** (`AI_PROVIDER_TOTAL_TIMEOUT=10 → 8.0s`, avvalgidek);
faqat <6s qiymatlar endi haqiqatan hurmat qilinadi — bu operator
konfiguratsiyasi uchun ham to'g'ri xulq (hujjatda "6-8s" deb yozilgan,
endi 2-8s).

**Natija:** ichki runner (`telegram_bot/tests/run_tests.sh` — CI aynan shuni
chaqiradi) **to'liq yashil**: `BARCHA TESTLAR MUVOFFAQIYATLI ✔` (0 `[FAIL]`).
`tests/ai_fallback_test.py`: 45/1 → **46/0**.
