# 🌱 STEP 2 — ORGANIC GROWTH: Action-Based Referral, Anti-Abuse & Time-To-First-Value

**Sana:** 2026-10-11
**Status:** ✅ Bajarildi — `bash tests/run_tests.sh` exit 0
**Tarmoq:** `telegram_bot/` (PTB + PostgreSQL), `tests/`

---

## 1. Nima o'zgardi (qisqacha)

| Talab | Yechim |
|---|---|
| Bonus faqat birinchi real amaldan keyin | `/start` → faqat **attribution**; mukofot → `ReferralService.register_first_action()` (post yaratish/rejalashtirish) |
| Anti-abuse (self, farming, double-claim) | 3 qatlamli filtr: self-referral + `signup_fingerprint` duplikat-detektori + atomik idempotent claim (`referral_rewarded_at`) |
| Post action tugmalari | AI Studio preview'ga [📋 Nusxalash] [🔄 Yangi variant] [🔗 Do'stlarga] qo'shildi ([📅 Rejalashtirish] mavjud edi); preview ekrani o'zgarmadi |
| Ixtiyoriy share → reklama YO'Q | Share faqat shaxsiy chatga havola yuboradi; `compose_post_text`/delivery zanjiri referalni umuman bilmaydi |
| TTFV + D1/D7 + referral konversiya `/stats` da | `record_first_value` (TTFV alias) generatsiya nuqtalarida; `/stats` gauge'iga `lg_referral_conv` qatori qo'shildi |

---

## 2. Action-based referal modeli

### 2.1 Oqim

```
/start ref_<id>
   └─ ReferralService.register_new_user()      [1 atomik tranzaksiya]
        • anti-abuse: self / takroriy / noma'lum referrer / duplicate-profil
        • INSERT users (referrer_id, signup_fingerprint, referral_block_reason)
        • reward = 0 — reward_status: none | pending_first_action | blocked
        • referrerga xabar: "do'st qo'shildi, mukofot birinchi postidan keyin"

BIRINCHI YAROQLI AMAL (post yaratish YOKI haftalik rejalashtirish)
   ├─ posts_repository.add_post()  hook ─┐  (lazy import, try/except — fail-soft)
   └─ scheduler_repository.schedule_week_posts() hook ─┘
        └─ ReferralService.register_first_action(user_id)   [1 atomik tranzaksiya]
             1) claim: UPDATE users SET referral_rewarded_at = NOW()
                WHERE ... AND referral_rewarded_at IS NULL
                      AND referral_block_reason IS NULL RETURNING referrer_id
                → parallel chaqiruvlardan FAQAT BITTASI g'olib (repeated-claim yo'q)
             2) ledger double-check (referrer + op='referral' + reference_id=user)
             3) referrer qatori FOR UPDATE → tarif = COUNT(konversiyalar)
                → CreditsService.grant/add_in_tx (balans + credits_ledger auditi)
             4) kesh invalidate + bildirishnoma navbatga (queue_reward_notice)
```

* Tarif jadvali **o'zgarmadi**: 1–3-do'st uchun +3, keyingilar +1
  (`referral_reward_for`), PRO berilmaydi. Farqi: hisob endi faqat
  **konversiya qilgan** (birinchi post yaratgan) do'stlar bo'yicha.
* Bildirishnoma: `scheduler.referral_reward_notices_job(bot)` — har 1 daqiqada
  navbatdan (bounded deque, maxlen=500) ≤25 tasini oladi va mavjud
  `referral_reward_notice` matnini yuboradi (`main.py`, id=`referral_reward_notices`).
* Konversiya **triggerlari**: qo'lda/AI/magic post saqlash (`add_post` — barcha
  8 sayt shu yerdan o'tadi) va Autopilot haftalik rejasi
  (`schedule_week_posts`). Jamoa workflow **draft** postlari atalay hisoblanmaydi.
* Hook'lar **fail-soft**: referal tizimi xatolansa ham post saqlanadi;
  `add_post` ning 3-cursor kontrakti buzilmagan (hook tranzaksiyadan keyin,
  alohida `db_transaction` orqali).

### 2.2 Anti-abuse filtrlari

| Filtr | Mexanizm | Natija |
|---|---|---|
| Self-referral | `validate_referral` (o'zgarmagan) | referrer biriktirilmaydi, bonus yo'q |
| Takroriy referral | mavjud user → referrer O'ZGARMAYDI | `already_referred` / `existing_user` |
| Noma'lum referrer | `SELECT` tekshiruvi | `unknown_referrer` |
| **Duplicate farming** | `signup_fingerprint = sha256(normalize(username)\|normalize(full_name))`; bir xil referrer ostida bir xil barmoq → `referral_block_reason='duplicate_profile'` | attribution saqlanadi, mukofot **doimiy** bloklanadi, tarif hisobiga kirmaydi |
| **Repeated claim** | shartli UPDATE (`referral_rewarded_at IS NULL`) + ledger double-check + `FOR UPDATE` | 1 do'st = 1 mukofot (parallel poygada ham) |

Telegram'da qurilma ID'si mavjud emas — shu sababli "device farming"ga qarshi
profil barmog'i (PII faqat SHA-256 hash ko'rinishida) + action-gate + tarif
hisobining faqat konversiyalarga bog'lanishi birgalikda fermer hisoblarining
iqtiyodiy foydasini nolga tushiradi.

### 2.3 Migratsiya (schema.sql)

* `ALTER TABLE users ADD COLUMN IF NOT EXISTS` × 3:
  `referral_rewarded_at TIMESTAMPTZ`, `referral_block_reason VARCHAR(32)`,
  `signup_fingerprint VARCHAR(64)` — yangi jadval/indeks YO'Q
  (schema_test 31/33 pinlari buzilmadi).
* EOF'da idempotent `DO $postassist_referral_backfill$` bloki: **legacy**
  allaqachon mukofotlangan juftliklar uchun (`credits_ledger` da
  `op='referral' AND reference_id=user_id` yozuvi bor) `referral_rewarded_at`
  to'ldiriladi → migratsiyadan keyin double-claim imkonsiz.

---

## 3. Post generatsiyasi ACTION tugmalari

Preview ekrani (`AI_TONE_SELECT`, `_studio_preview_text`) **o'zgarmadi** —
`get_ai_tone_keyboard` dagi uslub qatorlari va [📅 Rejalashtirish] o'z joyida.
Ostiga qo'shildi (3 tilda):

| Tugma | callback | Handler |
|---|---|---|
| 📋 Nusxalash / Копировать / Copy text | `ai_copy` | `ai_copy_post_callback` — matn alohida xabarda `<code>` blokida (bosilsa nusxalanadi), ≤3800 belgi |
| 🔄 Yangi variant / Новый вариант / Regenerate | `ai_regen` | `ai_tone_callback` yadrosi (joriy uslubda qayta generatsiya; kvota/rate-limit bir xil) |
| 🔗 Do'stlarga / Поделиться / Share referral | `ai_share_ref` | `ai_share_referral_callback` — havola + `switch_inline_query` share tugmasi |

* Uchalasi `REGISTERED_STATIC_CALLBACKS` da, ≤64 bayt, barcha handler'lar
  boshida `await query.answer()`.
* Magic Post ekrani (`_magic_action_keyboard`) **frozen** — tegilmadi.

### Ixtiyoriy ulashish = reklama YO'Q

`ai_share_referral_callback` faqat `query.message.reply_text` ishlatadi
(shaxsiy chat). Kanal publishing zanjiri (`scheduler.compose_post_text`,
`delivery_service`, ad-injection) referal havolani **umuman bilmaydi** —
bu yangi testda manba skani bilan qotirilgan: `compose_post_text` da
`ref_`/`referral`/`start=ref` tokenlari yo'q, share handler'da
`scheduled_posts`/`add_post`/`delivery_service`/`ad_free` chaqiruvlari yo'q.

---

## 4. Retention & onboarding telemetriyasi

* **TTFV** (`/start` → birinchi post **generatsiyasi/rejalashtirilishi**):
  * `services.onboarding_telemetry.record_first_value` — `record_first_post`
    alias'i (birinchi qiymat ustuvor, idempotent); `ttfv_seconds = ttfp_seconds`.
  * Yangi qayd nuqtalari (best-effort, oqimni buzmaydi): AI Studio
    generatsiyasi (`_studio_generate_and_preview`), Magic Post generatsiyasi,
    `add_post`, `schedule_week_posts`.
* **Referral konversiya statistikasi**:
  `users_repository.get_referral_conversion_stats(days=30)` →
  `{window_days, referred_total, converted, blocked, rate}` (FILTER-based
  bitta so'rov; xatoda `{}`); `database.py` facade'da re-eksport.
* **`fetch_report`** endi `report["referral"]` blokini ham qaytaradi —
  `hasattr`-guard (eski db-fake'lar uchun hisobot o'zgarmaydi) + alohida TTL
  kesh (`reset_cache` ikkalasini tozalaydi) + fail-soft.
* **`/stats`** (admin gauge bloki): D1/D7 retention yonida yangi qator —
  `lg_referral_conv` (uz/ru/en): `🤝 Referral konversiyasi: <b>{percent}%</b>
  ({converted}/{referred} do'st birinchi post yaratdi)`. Blok FAQAT referral
  ma'lumoti mavjud bo'lganda chiziladi — eski matnlar 100% o'zgarmaydi.

---

## 5. i18n (uz / ru / en)

Yangi kalitlar: `ai_btn_copy`, `ai_btn_regen`, `ai_btn_share_ref`,
`ai_copy_done`, `ai_copy_empty`, `ai_share_ref_text {link}`,
`referral_friend_joined_notice`, `lg_referral_conv {percent}{converted}{referred}`.

O'zgartirilgan: `referral_menu` — "+3"/"+1" tarifi va `{credits}{count}{link}`
placeholder'lari **saqlandi**, action sharti ("birinchi post yaratgach")
qo'shildi. `referral_reward_notice` (konversiya xabari) so'zlashuvi qotirilgan
pinlari o'zgarmadi ("AI ball" / "ИИ-балл" / "AI credit").

Barcha inline yorliqlar ≤18 ko'rinadigan belgi (postassist_polish standarti).

---

## 6. Testlar

### Yangi: `tests/organic_growth_referral_ttfv_test.py` (175 tekshiruv)

Static: action-model API kontrakti, bildirishnoma navbati + job (fake bot),
hook wiring/fail-soft/cursor-kontrakt skanlari, tugmalar 3 tilda + registry +
`query.answer`, ad-free skanlar, TTFV + `fetch_report["referral"]` + gauge
render, i18n paritet. Live (pgserver): /start→pending→bonus, REAL `add_post`
hook'i, takroriy amal, duplicate farming blok, self-referral, konversiya
statistikasi hisob-kitobi.

### Yangilangan (xatti-harat o'zgarishi sababli)

* `tests/credits_referral_test.py` — live bo'lim ikki fazali: /start
  (reward=0, ledger bo'sh) → birinchi amal (+3, ledger) → takror
  (`already_rewarded`); yangi 2b-bo'lim: duplicate farming + tarif hisobi.
* `tests/concurrency_load_test.py::test_parallel_referral` — ikki faza:
  25 parallel /start (attribution, bonus yo'q) + 25 parallel konversiya
  (hot-row FOR UPDATE poygasi; yig'indi = tarif jadvali, ledger=25, zanjir butun).
* `tests/stress_concurrency_test.py::test_live_50_parallel_credits_referral` —
  faza A: 50 credits + 50 /start; faza B: 50 parallel `register_first_action`
  (DB_POOL_MAX≤5, deadlock/starvation yo'q, balans = 100+150+tarif(50)).
* `tests/unit_test.py` — tone klaviaturasi pini 7→10 tugma (yangi action
  tugmalari talab qilingan o'zgarish).

### Regressiya yo'q

`bash tests/run_tests.sh` → **exit 0** (barcha 112 test chaqiruvi yashil;
schema_test, unit_test, i18n paritetlari, postassist_polish, onboarding,
credits_referral, concurrency, load, stress, p0 pytest — hammasi).

---

## 7. Xavfsizlik / operatsion eslatmalar

* Bildirishnoma navbati **jarayon xotirasida** (bounded) — bot qayta ishga
  tushsa pending xabarlar yo'qolishi mumkin; mukofotning o'zi (balans +
  `credits_ledger`) bazada DOIMY, shu sababli bu faqat kosmetik yo'qotish.
* `signup_fingerprint` — PII hash (SHA-256), qayta tiklanmaydi; faqat
  duplikat-deteksiya uchun.
* Barcha referal yozuvlari `credits_ledger` da (`op='referral'`,
  `reference_id=<do'st ID>`) — to'liq audit zanjiri (`balance_after`).
* Hook'lar tranzaksiyadan TASHQARIDA va fail-soft: referal/BP xatosi post
  saqlash yoki rejalashtirishni hech qachon to'xtatmaydi.

## 8. Asosiy fayllar

| Fayl | O'zgarish |
|---|---|
| `telegram_bot/services/referral_service.py` | action-based model (to'liq qayta yozilgan) |
| `telegram_bot/schema.sql` | 3 ustun + legacy backfill DO-bloki |
| `telegram_bot/repositories/users_repository.py` | `get_referral_conversion_stats` |
| `telegram_bot/repositories/posts_repository.py` | `add_post` konversiya hook'i |
| `telegram_bot/repositories/scheduler_repository.py` | haftalik reja hook'i + TTFP |
| `telegram_bot/database.py` | facade re-eksport |
| `telegram_bot/handlers/start.py` | friend-joined bildirishnomasi |
| `telegram_bot/handlers/ai_assistant.py` | copy/regen/share handlerlari + TTFV |
| `telegram_bot/handlers/magic_post.py` | TTFV belgisi (klaviatura frozen) |
| `telegram_bot/handlers/admin.py` | `/stats` konversiya qatori |
| `telegram_bot/keyboards/inline.py`, `callback_data.py` | action tugmalari + registry |
| `telegram_bot/scheduler.py` | `referral_reward_notices_job` |
| `telegram_bot/main.py` | 1-daqiqalik flush job |
| `telegram_bot/services/onboarding_telemetry.py` | TTFV alias + referral blok |
| `telegram_bot/locales/*`, `telegram_bot/translations/admin_panel.py` | i18n |
| `tests/*` | yangi + yangilangan testlar (yuqorida) |
