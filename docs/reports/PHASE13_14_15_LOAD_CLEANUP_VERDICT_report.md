# 🏁 PHASE 13, 14 & 15 — YUKLAMA/STRESS TEST, FINAL CLEANUP VA YAKUNIY PRODUCTION VERDICT

**Sana:** 2026-09-16 · **Branch:** `arena/01a0a8cb-yordamchibot` · **Baza:** `0751556` (PR #131 merge)
**Buyruq:** `PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh`

```
BASH EXIT CODE: 0
[FAIL] qatorlari soni: 0
```

> **57-band (soxta PASS taqiqlanadi):** quyidagi har bir raqam ushbu sessiyada
> **haqiqatan ishga tushirilgan** test chiqishidan olindi. Test qilinmagan
> narsa "PASS" deb yozilmagan — muhit cheklovlari `NOT TESTED` deb belgilangan
> (bu sessiyada ularning soni **0**, chunki `pgserver` orqali real PostgreSQL
> ko'tarildi).

---

## A) O'ZGARTIRILGAN FAYLLAR

`git diff --stat` natijasi: **25 ta fayl o'zgartirildi, 2 ta yangi fayl qo'shildi**
(jami `145 insertions(+), 164 deletions(-)`).

### A.1 Yangi fayllar

| Fayl | Qator | Vazifa |
|---|---|---|
| `tests/concurrency_load_test.py` | **1170** | **PHASE 13 (39-band)** — yuklama va konkurentlik suite'i |
| `tests/requirements-test.txt` | 27 | **PHASE 14 (56-band)** — test-only bog'liqliklar (`pytest`, `pgserver`, `pyflakes`) |

### A.2 PHASE 13 — P0 bug tuzatilishi (1 fayl)

| Fayl | O'zgarish |
|---|---|
| `telegram_bot/services/ai/orchestrator.py` | `+55/-2` — **P0-01** tuzatildi: `INTENT_QUOTA_OPERATIONS` xaritasi + `_quota_operation_type()` qo'shildi |

### A.3 PHASE 14 — dead code / unused import tozaligi (22 fayl)

| Fayl | O'zgarish | Nima olib tashlandi |
|---|---|---|
| `telegram_bot/handlers/new_post.py` | `-73` | **o'lik funksiya** `_save_and_finish()` (67 qator) + 2 unused import |
| `telegram_bot/handlers/health.py` | `-24` | **o'lik funksiya** `admin_health_callback()` |
| `telegram_bot/handlers/ai_assistant.py` | `-18` | 8 unused import (`BTN_BACK`, `BTN_MAIN_MENU`, `apply_pro_audit_stage`, `_AUDIT_*`, `_PRO_POST_ENHANCEMENT`, `_FREE_POST_HINT`, `reservation_source`) |
| `telegram_bot/keyboards/default.py` | `-10` | **o'lik funksiya** `_image_post_label()` |
| `telegram_bot/handlers/pending.py` | `-7/+3` | 6 unused import |
| `telegram_bot/database.py` | `-6` | **o'lik funksiya** `_invalidate_stats()` + `dtime` import |
| `telegram_bot/handlers/converter.py` | `-5/+2` | 5 unused import |
| `telegram_bot/handlers/queue.py` | `-5/+2` | `json`, `ReplyKeyboardMarkup`, `get_main_keyboard` |
| `telegram_bot/services/subscription_service.py` | `-4` | `psycopg2`, `FREE_QUEUE_MAX_POSTS`, `_normalize_language_code` |
| `telegram_bot/handlers/admin.py` | `-3/+1` | `BTN_MAIN_MENU`, `BTN_CANCEL`, `get_sponsors_delete_keyboard` |
| `telegram_bot/middlewares/fsm_cleaner.py` | `-3/+1` | `typing.Any`, `ConversationHandler` |
| `telegram_bot/services/ai/orchestrator.py` | (yuqorida) | `ValidationResult`, `AIProvider`, `AIProviderError`, `AIQueueTimeoutError` |
| `telegram_bot/services/ai/providers.py` | `-2` | `asyncio`, `typing.Any` |
| `telegram_bot/handlers/settings.py`, `start.py`, `channels.py`, `magic_post.py`, `channel_extract.py`, `content_calendar.py`, `scheduler.py`, `utils/web_server.py`, `services/ai/validator.py` | `-1…-2` har biri | bittadan unused import |
| `telegram_bot/utils/ai_agent.py` | `+7/-2` | **qaytarildi + hujjatlandi** (pastdagi P1-01 ga qarang) |
| `.gitignore` | `+49/-6` | log/temp/pytest/pgserver/IDE qoidalari |
| `tests/run_tests.sh` | `+27` | PHASE 13 bo'limi runner'ga ulandi |

**Tozalash mezonlari (qat'iy):** nom butun repoda (`*.py`, `*.sh`, `*.md`,
`*.sql`) **faqat o'z `def` qatorida** uchrasa va top-level + dekoratorsiz bo'lsa
o'chirildi. Barcha `__init__.py` re-export hub'lari, `content_menu.py` backward-compat
shim'i va `keyboards/inline.py` alias'lari **saqlab qolindi** — legacy callback
mosligi buzilmadi.

**Natija:** production kodda unused import **106 → 55**. Qolgan 55 taning
barchasi qasddan qilingan re-export:

| Joy | Soni | Nega saqlandi |
|---|---|---|
| `locales/__init__.py` | 27 | i18n re-export hub (`# noqa: F401`) |
| `translations/__init__.py` | 8 | tarjima re-export hub |
| `utils/ai_agent.py` | 6 | provayder kalitlari — testlar `ai_agent.<KEY>` ni monkeypatch qiladi |
| `handlers/content_menu.py` | 6 | backward-compat shim (`import *`) |
| `handlers/__init__.py` | 4 | router re-export hub |
| `keyboards/inline.py` | 3 | callback re-export (eski importlar uchun) |
| `main.py` | 1 | `pytz` — `# noqa` bilan belgilangan |

---

## B) TOPILGAN VA TUZATILGAN BUGLAR

### 🔴 P0 — production'ni bloklab turgan

#### P0-01 — `AIOrchestrator` haqiqiy DB bilan **100% ishlamas edi**

* **Fayl:** `telegram_bot/services/ai/orchestrator.py:98` (eski)
* **Kod:** `res = await reserve_ai_quota(db, user_id, f"ai_{intent.value.lower()}", 1)`
* **Muammo:** `database.AI_OPERATION_TYPES` oq ro'yxati quyidagicha:
  `('ai_chat','ai_studio','magic_post','voice_post','image_post','post_score','post_enhancer','content_calendar','other')`.
  Orchestrator yuborgan 8 ta qiymatning **hech biri** bu ro'yxatda yo'q:

```
OLD op types : ['ai_create_post', 'ai_improve_post', 'ai_shorten', 'ai_expand',
                'ai_generate_variants', 'ai_post_audit', 'ai_content_ideas', 'ai_unknown']
valid in whitelist: []   ← 0 ta yaroqli
```

  `reserve_ai_request()` esa `op_base not in AI_OPERATION_TYPES` bo'lganda
  darhol `invalid_request` bilan rad etadi. Ya'ni `orchestrate(db_module=<haqiqiy database>)`
  **har doim** `QUOTA_EXCEEDED` qaytarar edi — foydalanuvchi AI javobini hech
  qachon olmasdi (fail-closed, lekin 100% rad).
* **Nega avval ko'rinmagan:** mavjud testlar `reserve_ai_quota` ni **mock** qiladi
  (`tests/ai_orchestrator_test.py:275`) yoki `db_module=False` uzatadi
  (`:251`, `:342`) — ya'ni haqiqiy validatsiya yo'li hech qachon yurilmagan.
  Bu bug **faqat real DB bilan yuklama testida** ochildi.
* **Tuzatish:** intent → oq ro'yxatdagi aniq operatsiya turi xaritasi:
  `CREATE_POST/GENERATE_VARIANTS→magic_post`, `IMPROVE_POST/SHORTEN/EXPAND→post_enhancer`,
  `POST_AUDIT→post_score`, `CONTENT_IDEAS→content_calendar`, `UNKNOWN→ai_chat`.
  Qo'shimcha himoya: `_quota_operation_type()` javobni **runtime'da ham**
  `AI_OPERATION_TYPES` bo'yicha tekshiradi — kelajakda ro'yxat o'zgarsa ham
  100% rad holati qaytmaydi.
* **Isbot:** tuzatishdan keyin 100 ta parallel virtual foydalanuvchining
  **100 tasi ham** muvaffaqiyatli javob oldi (oldin 0 ta).

### 🟠 P1 — test/CI yaxlitligi

#### P1-01 — Dead-code tozalash provayder kalitlarini buzdi (o'z vaqtida ushlandi)

* **Nima bo'ldi:** `utils/ai_agent.py` dagi `GROQ_API_KEY`, `OPENROUTER_API_KEY`,
  `MISTRAL_API_KEY`, `CEREBRAS_API_KEY`, `SAMBANOVA_API_TOKEN`, `CLOUDFLARE_API_TOKEN`
  importlari pyflakes tomonidan "unused" deb topildi va o'chirildi.
* **Oqibat:** `telegram_bot/tests/unit_test.py:6051-6060` ushbu nomlarni
  **monkeypatch** qiladi (`ai_agent.SAMBANOVA_API_KEY = "test-key"`) →
  `AttributeError: module 'utils.ai_agent' has no attribute 'GROQ_API_KEY'`.
* **Aniqlanishi:** to'liq suite ishga tushirildi va **`RUNNER EXIT=1`** qaytdi.
* **Tuzatish:** importlar **qaytarildi** va "bu public sirt, unused emas" deb
  izoh bilan hujjatlandi. Suite qayta yashil.
* **Xulosa:** "pyflakes unused" ≠ "o'lik kod". Shu sababli tozalash faqat
  **butun repo bo'yicha 1 ta uchraydigan** nomlar bilan cheklandi.

### 🟡 P2 — test infratuzilmasi

#### P2-01 — Yuklama testidagi `_scalar()` INSERT'i ROLLBACK bo'lib ketardi

`db_cursor(commit=False)` ichida `INSERT ... RETURNING id` bajarilsa, yozuv
qaytariladi. Natijada karta chek testi `not_found` olardi. Alohida
`_insert_returning_id()` (majburiy `commit=True`) qo'shildi.

#### P2-02 — Thread-leak tekshiruvi soxta pozitiv berardi

`asyncio.to_thread` ning default executor threadlari **event loop yopilguncha**
tirik turadi. Leak'ni loop **ichida** o'lchash har doim "leak" ko'rsatardi.
O'lchov `asyncio.run()` **chegarasi tashqarisiga** ko'chirildi.

#### P2-03 — Test-only bog'liqliklar hujjatlanmagan edi

`pytest` va `pgserver` bo'lmasa suite'lar **jim skip** qiladi — "yashil" natija
to'liq qamrovni anglatmasdi. `tests/requirements-test.txt` qo'shildi.

### 🟢 P3 — kuzatuv, tuzatish talab qilmaydi

`AIConcurrencyManager._cancelled_generations` va `_refunded_reservations`
to'plamlari o'sib boradi. O'lchov: **300 ta yozuv → RSS Δ = 0.0 MB** (20 MB
chegaradan ancha past). Uzoq umrli jarayon uchun kuzatuvda qoldirildi.

---

## C) AI IMPROVEMENTS — oldingi holat vs yangi

| Jihat | Oldingi holat | Hozirgi holat |
|---|---|---|
| **Orchestrator + real DB** | ❌ 100% `invalid_request` — AI ishlamasdi | ✅ 100/100 so'rov muvaffaqiyatli |
| Operatsiya turi | `f"ai_{intent}"` — oq ro'yxatdan tashqari | `INTENT_QUOTA_OPERATIONS` xaritasi + runtime validatsiya |
| Kvota | Phase 2 atomik `reserve_ai_request` (to'g'ri, lekin chaqirilmayotgan edi) | Endi **haqiqatan** atomik bron orqali |
| Provider zanjiri | Gemini → Groq → OpenRouter → Mock | O'zgarmagan (regressiya yo'q) |
| Advanced SMM (Phase 11/12) | variants / repurpose / audit / planner | O'zgarmagan, 167 testi yashil |
| Concurrency | `run_with_queue` mavjud, lekin real yukda sinalmagan | **148 ta yangi tekshiruv** bilan isbotlangan |

---

## D) MENU & UX

Bu sessiyada **menyu/UX o'zgartirilmadi** — regressiya qo'riqonlari orqali
tasdiqlandi:

* Asosiy menyu **qat'iy 6 tugma** (uz/ru/en) — `o'tdi=167, xato=0`
* Kontent yaratish submenu + action-first — `o'tdi=268, xato=0`
* Yakuniy acceptance (TEST A..AG) — `o'tdi=566, xato=0`
* **Legacy routing saqlangan:** `AG4` testlari eski admin matnlari
  («📢 Majburiy obuna», «📊 To'liq statistika», «🎯 Reklama markazi»,
  «⚙️ AI parametrlar», «🗄️ DB / Kesh holati» …) **alias ro'yxatida qolganini
  va router'da handler topishini** tasdiqlaydi — hammasi `[OK]`.
* O'chirilgan `admin_health_callback` legacy routing'ni buzmaydi: `adm_health`
  callback'i `handlers/admin.py:641` da mustaqil ishlanadi (testlar tasdiqladi).

---

## E) CONCURRENCY & LOCKS

**Konfiguratsiya:** `MAX_AI_CONCURRENCY=5`, `MAX_AI_QUEUE=20`,
`AI_QUEUE_TIMEOUT=30s`, `DB_POOL_MAX=5`, `UserLockManager(default_timeout=1.0)` —
10-20 soniyalik bloklab qo'yuvchi lock yo'q.

| Kafolat | Isbot (real natija) |
|---|---|
| Semafor chegarasi **aynan** ushlanadi | peak parallellik **= 5** (`<=` emas, `==`), 50/50 bajarildi |
| Bounded queue fail-closed | 50 user burst → **42 QUEUE_FULL**, hech biri javobsiz qolmadi |
| QUEUE_FULL da to'liq refund | `refunded=42 == queue_full=42` |
| Navbatdan keyin menejer toza | `active=0, waiting=0, tracked=0, task_metadata=0` |
| asyncio task leak yo'q | barcha ssenariylarda `leaked_tasks <= 0` |
| Thread leak yo'q | barcha ssenariylarda `leaked_threads <= 0` |
| Non-blocking user lock | `UserLockTimeoutError` qisqa timeout bilan (10-20s qotish yo'q) |
| Request cancellation | kechikkan natija rad etiladi + kvota qaytadi |

**Yuklama ssenariylari natijalari:**

| Ssenariy | Natija | Vaqt |
|---|---|---|
| 10 virtual user (kelish 0.5s) | **10/10 success**, 0 rad | 0.48s |
| 25 virtual user | **25/25 success**, 0 rad | 0.51s |
| 50 virtual user | **50/50 success**, 0 rad | 0.52s |
| Semafor to'yintirilishi (50 burst) | 50/50, peak **= 5** | 0.33s |
| BURST 50 (queue=6) | 15 success / **35 fail-closed** | 0.26s |
| **100 virtual user (TO'LIQ YUKLAMA)** | **100/100 success**, 0 rad | 1.01s |
| Soak 5×10 to'lqin | 50/50, RSS barqaror | — |

---

## F) DATABASE & TRANSACTIONS

`database.py` da **9 ta `SELECT … FOR UPDATE`** qator qulfi. Barcha race
condition'lar **real PostgreSQL 16.2** (`pgserver`, `DB_POOL_MAX=5`) ustida
tekshirildi:

| Race | Parallel | Natija |
|---|---|---|
| Kvota bron (bitta user, kvota=5) | **50** | AYNAN **5** ruxsat, 45 rad, `ai_requests_today=5` (limitdan oshmadi), `db_error=0` |
| Refund idempotency | **10** | AYNAN **1** marta qaytdi, 9 tasi `already_refunded`, kvota 1 ga kamaydi |
| Stars to'lov (bitta `charge_id`) | **25** | AYNAN **1** marta PRO, 24 `duplicate`, `payments` da 1 qator, obuna **30 kun** (25× emas) |
| Karta chek tasdiqlash | **10** | AYNAN **1** marta PRO, UZS ledger 1 qator, status `approved` |
| Referral bonus (bitta referrer) | **25** | 25 ta biriktirildi, mukofot **31 == 31** (tarif jadvaliga mos), **double-grant yo'q**, ledger `balance_after` zanjiri butun |
| Promo kod (`max_uses=1`) | **10** | AYNAN **1** faollashdi |
| **ARALASH YUK** (kvota+to'lov+referral+promo) | **50** | **deadlock yo'q**, pool timeout yo'q, manfiy balans yo'q, yetim bron yo'q |

**Qo'shimcha kafolatlar:** har ssenariydan keyin `get_db_pool_status()` →
`used=0` (ulanish leak yo'q); `credits_ledger.balance_after` zanjiri parallel
yozuvda ham uzilmagan; bron qatorlari har doim `muvaffaqiyat + rad` ga teng.

---

## G) PAYMENT & SECURITY

| Himoya | Isbot |
|---|---|
| Stars duplicate charge | `10 parallel: 1 ta yangi to'lov, 9 ta duplicate` |
| `charge_id` UNIQUE | `schema.sql` + `uq_payments_telegram_charge_id` |
| Bo'sh `charge_id` | `invalid_payment` (rad) |
| Chek idempotency | `receipt:<id>` kaliti UNIQUE — ledger'da 1 qator |
| `pre_checkout` validatsiya | payload/user/amount/currency qat'iy; buzilgan → rad |
| Invoice manipulyatsiya | noto'g'ri amount/user/currency → rad |
| **RBAC fail-closed** | `RBAC: DB xatosida oddiy user admin EMAS` / `ruxsat YO'Q` |
| **RBAC tampering** | `adm_grant_pro:777`, `adm_promo:owner`, `adm_ai:123456789` → **baribir rad** |
| Admin callback'lar oddiy userga | `AG5` — barcha `adm_*` rad etildi |
| Kvota fail-closed | `database xatosida PRO berilmaydi (FAIL-CLOSED)` |
| HTML sanitizer | 34 test, idempotent, XSS escape |

---

## H) I18N STATUS

| Lug'at | `in_sync` | missing | extra | format_mismatch |
|---|---|---|---|---|
| `content_menu` | **True** | yo'q | yo'q | yo'q |
| `settings_stats` | **True** | yo'q | yo'q | yo'q |
| `channels_queue` | **True** | yo'q | yo'q | yo'q |
| `magic_post` | **True** | yo'q | yo'q | yo'q |
| `voice_post` | **True** | yo'q | yo'q | yo'q |
| `post_score` | **True** | yo'q | yo'q | yo'q |

* **UZ/RU/EN pariteti:** 100% (`translation_parity_report: EN kamchiliksiz`)
* **Hardcode matn yo'q:** `handlers/__init__.py` da `'Magic Post bilan'`,
  `'Asosiy menyu"'`, `'Iltimos, '` — barchasi `[OK]` (i18n orqali)
* **Queue-full xabari 3 tilda:** `⏳ AI hozir juda band…` / `…очень занят…` /
  `…very busy…` — barchasi mavjud
* **Tugma soni pariteti:** main / content / ai_studio / settings / tools /
  user_stats / channel_panel — uchala tilda bir xil

---

## I) TEST RESULTS — har bir suite bo'yicha

Barcha suite'lar `PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh` orqali
**haqiqiy PostgreSQL 16.2** (`pgserver`) bilan ishga tushirildi.

| # | Suite | Natija |
|---|---|---|
| 1 | Syntax (132 fayl kompilyatsiya + import) | **PASS** — 0 xato |
| 2 | 3-BOSQICH PRODUCTION ACCEPTANCE (18) | **PASS** — 129/0 |
| 3 | ✨ MAGIC POST | **PASS** — 155/0 |
| 3a | 📸 IMAGE → POST | **PASS** — 30/0 |
| 3a' | 📸 IMAGE → POST 3-bosqich | **PASS** — 180/0 |
| 3b | 🎙 VOICE → POST | **PASS** — 86/0 |
| 3c | 📊 POST SCORE & IMPROVER | **PASS** — 214/0 |
| 3d | 🧭 UX V2 (6 tugma) | **PASS** — 167/0 |
| 3e | 🧩 KONTENT YARATISH submenu | **PASS** — 268/0 |
| 3f | 📢 KANALLARIM + 📅 REJALASHTIRILGAN | **PASS** — 259/0 |
| 3g | 📊 STATISTIKA + ⚙️ SOZLAMALAR + RBAC | **PASS** — 296/0 |
| 3h | 🗓 SMART CONTENT CALENDAR | **PASS** — 25/0 |
| 3i | 🔄 2-QADAM REFAKTORI | **PASS** — 170/0 |
| 3j | ⚙️ 3-QADAM REFAKTORI | **PASS** — 227/0 |
| 3k | 🧭 4-QADAM + YAGONA INLINE ADMIN | **PASS** — 279/0 |
| 3l | 🏁 YAKUNIY ACCEPTANCE (A..AG) | **PASS** — 566/0 |
| 3m | 📊 STATISTIKA IZOLYATSIYASI | **PASS** — 197/0 |
| 3n | ✨ AI PROMPT SIFATI | **PASS** — 155/0 |
| 3o | 🔒 ATOMIK KVOTA + KREDIT | **PASS** — 161/0 |
| 3p | HTML SANITIZER + DELIVERY | **PASS** — 34 tests |
| 3q | 🔒 FSM TOZALASH | **PASS** — 19 tests |
| 3r | 🤖 AI ORCHESTRATOR | **PASS** — 167/0 |
| 3s | ⚡️ AI CONCURRENCY & USER LOCK | **PASS** |
| 3t | 💳 TO'LOVLAR + SCHEDULER | **PASS** — 19 tests |
| 3u | 🚀 PHASE 11 & 12 ADVANCED SMM | **PASS** — 167/0 |
| **3v** | **⚡️ PHASE 13 YUKLAMA/KONKURENTLIK (YANGI)** | **PASS — 148/0, NOT TESTED=0** |
| 4 | unit_test (regressiya) | **PASS** — 2556/0 |
| 4 | services / scheduler / new_requirements | **PASS** — 148/0 · 171/0 · 61 |
| 4 | album/skip · album-warning · photo-leak | **PASS** — 104 · 171 · 43 |
| 4 | i18n (ai_parity · full_parity · account · reply) | **PASS** — 24 · 243 · 352 · 428 |
| 4 | schema · db_integrity · ai_mock · ai_fallback | **PASS** — 344 · 65 · 133 · 176 |
| 4 | RBAC · health · credits_referral | **PASS** — 52 · 14 · 46 |
| 4 | **P0 CONCURRENCY (pytest + live PG)** | **PASS** — 4 passed |
| 4 | **LOAD TEST (live PG, 250 post)** | **PASS** — 174/0 |
| 4 | **STRESS & CONCURRENCY (9-bosqich)** | **PASS** — 251/0 |
| 4 | YAKUNIY ACCEPTANCE (10-bosqich) | **PASS** — 118/0 |
| 4 | PRODUCTION PAYMENTS P0 | **PASS** — 9 tests |
| 4 | PRODUCTION FINAL ACCEPTANCE (11-bosqich) | **PASS** — 147/0 · 115/0 |

**JAMI: `[FAIL]` qatorlari = 0 · `NOT TESTED` = 0 · `BASH EXIT CODE: 0`**

### Muhit haqiqatlari (shaffoflik uchun)

```
CPU: 2 yadro · MemAvailable: 3616.1 MB · RSS(start): 22.9 MB · DB_POOL_MAX: 5
Live PostgreSQL: postgresql://postgres:@/postgres?host=/tmp/yordamchi_pg_load39
PostgreSQL 16.2 on x86_64-pc-linux-gnu
FREE kunlik kvota=5, virtual user krediti=3 → har user maksimal 8 ta so'rov
```

2 yadro + 3.6 GB muhit **100 ta virtual foydalanuvchini ko'tardi** — shu sababli
`NOT TESTED — resource limit` qayd etilmadi (chegara: ≥2 yadro va ≥900 MB).
Agar muhit past bo'lsa, suite o'zi aniq shu yozuvni chiqaradi va yiqilmaydi.

---

## J) REMAINING RISKS

### Infratuzilmaviy / tashqi (kod tashqarisida)

1. **Real AI provayderlari sinovdan o'tmagan.** Barcha testlar deterministik
   `LoadProvider`/`MockProvider` bilan yuradi. Gemini/Groq/OpenRouter'ning real
   rate-limit, 429 va timeout xatti-harakati **faqat fallback zanjiri darajasida**
   tekshirilgan. Production'da birinchi soatlarda provayder metrikalari
   kuzatilishi kerak.
2. **DB pool `DB_POOL_MAX=5` ga nisbatan sinovdan o'tdi.** Production'da pool
   kattaroq bo'lsa yaxshi, lekin Neon/Render ulanish limiti bilan mosligi
   deploy'da tekshirilishi shart.
3. **Telegram API real emas.** `FloodWait`/`RetryAfter` simulyatsiya qilingan;
   real Telegram cheklovlari farq qilishi mumkin.
4. **Sentrifikatsiya:** `ai_concurrency_manager` global singleton — bir nechta
   worker (multi-process) deploy'da har bir jarayon o'z limitiga ega bo'ladi,
   ya'ni umumiy parallellik `workers × MAX_AI_CONCURRENCY` ga teng.
5. **Test-only bog'liqliklar** (`pytest`, `pgserver`) production image'ga
   kirmaydi — CI'da `tests/requirements-test.txt` o'rnatilishi shart, aks holda
   live-DB suite'lari jim skip bo'ladi.

### Kod darajasidagi qoldiq xatarlar

6. **P3:** `AIConcurrencyManager` ichki to'plamlari (`_cancelled_generations`,
   `_refunded_reservations`) o'sib boradi. O'lchov: 300 yozuv → 0.0 MB. Uzoq
   umrli jarayonda (haftalab restart'siz) nazariy o'sish mumkin — kuzatuvda.
7. **Legacy yuza:** `handlers/content_menu.py` (`import *`) va bir qator
   alias'lar backward-compat uchun ataylab saqlangan — ular pyflakes'da
   "unused" ko'rinadi, lekin o'chirish **eski oqimlarni buzadi**.
8. **`telegram_bot/tests/unit_test.py`** da 5 ta `timedelta` redefinition va
   test fayllarida jami ~150 unused import qoldi. Bular **test kodiga** tegishli
   va production'ga ta'sir qilmaydi; alohida bosqichda tozalanishi mumkin.

---

## K) PRODUCTION VERDICT

# ✅ PRODUCTION READY — shartli

### Asos

| Mezon | Holat |
|---|---|
| To'liq suite | **`BASH EXIT CODE: 0`**, `[FAIL]=0` |
| Yuklama (39-band) | 10/25/50/**100** parallel user — barchasi yashil |
| Bounded queue xavfsizligi | fail-closed + 100% refund isbotlangan |
| Deadlock | 50 parallel aralash yuk — **0 deadlock** |
| Resurs leak | task=0, thread=0, pool=0, RSS barqaror |
| Payment idempotency | Stars + chek — parallel'da aynan 1 marta |
| RBAC | fail-closed + tampering himoyasi |
| i18n | UZ/RU/EN 100% paritet, hardcode yo'q |
| P0 bug | **topildi va tuzatildi** (P0-01) |

### Nega "shartli"

Verdict **kod sifati bo'yicha qat'iy ijobiy**, lekin quyidagi **deploy shartlari**
bajarilishi kerak:

1. **Deploy'dan keyin AI oqimini real tekshirish.** P0-01 aynan shu yo'lda edi
   va mock-testlar uni ko'rmadi. Production'da bitta haqiqiy Magic Post /
   AI Studio so'rovi yuborib, javob kelishini ko'z bilan tasdiqlash shart.
2. **AI provayder kalitlarini sozlash** (`GEMINI_API_KEY` / `GROQ_API_KEY` / …)
   — aks holda barcha so'rovlar `MockProvider`ga tushadi.
3. **`MAX_AI_CONCURRENCY` / `MAX_AI_QUEUE` ni real quvvatga moslash** va
   multi-worker deploy'da umumiy limitni hisobga olish.
4. **CI'da `tests/requirements-test.txt` ni o'rnatish** — aks holda live-DB
   suite'lari skip bo'lib, regressiya ko'rinmay qoladi.
5. **Monitor:** DB pool `used`, `ai_reservations.status='active'` qoldiqlari,
   `credits_ledger` balansi, Sentry xatolari.

Ushbu 5 band bajarilsa — **production'ga chiqarish xavfsiz**.

---

## Ilova: takrorlash buyrug'i

```bash
# Test-only bog'liqliklar (live-DB suite'lari uchun)
python -m pip install -r telegram_bot/requirements.txt -r tests/requirements-test.txt

# To'liq suite
PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh
echo "BASH EXIT CODE: $?"

# Faqat PHASE 13 (yuklama/konkurentlik)
python tests/concurrency_load_test.py

# Dead-code nazorati (PHASE 14)
python -m pyflakes telegram_bot tests
```
