# 🔍 POSTASSIST — PHASE 0: TO'LIQ KOD BAZASI AUDITI

> **Yangi "AI Kanal Operatori" funksiyalarini xavfsiz qo'shish uchun tayyorgarlik hisoboti**
> (Channel DNA · 7-Day Autopilot · Smart Best Time · URL→Post · RSS · Content Recycle)

| Metama'lumot | Qiymat |
|---|---|
| Repozitoriy | `samandar20222004-design/yordamchibot` |
| Audit olib borilgan commit | `c4b563837a710dbd9df04d6b1b7f82a4408beed3` (`main`) |
| Ishchi branch | `arena/01a0a9e4-yordamchibot` |
| Audit sanasi | 2026-09-16 |
| Kod hajmi | 134 `.py` fayl · ~99 900 satr · 22 DB jadvali · 63 test fayli |
| **Production kodga tegildimi?** | **YO'Q — 0 fayl o'zgartirildi** (`git status` toza) |
| Audit usuli | Statik tahlil (fayl:satr) + **runtime eksperimentlar** (venv'da, kod o'zgartirmasdan) + `schema.sql` migratsiya tahlili |

---

## 0. XULOSA (EXECUTIVE SUMMARY)

### 0.1. Umumiy baho

Kod bazasi **kutilganidan ancha pishiq va yaxshi hujjatlashtirilgan**: 22 jadval, idempotent migratsiya mexanizmi,
`post_deliveries` idempotentligi, atomik AI kvotasi, RBAC, 3 tillik paritet, 60+ test. Scheduler ham barqaror
(restart recovery, FloodWait siyosati, UNKNOWN_DELIVERY himoyasi, backoff).

Biroq **yangi AI Kanal Operatori funksiyalarini aynan shu poydevorda qo'shish xavfli**, chunki topilgan 3 ta
tizimli muammo aynan yangi funksiyalar ishlatadigan qatlamda joylashgan:

1. **`services/ai/*` zanjiri production'da Mock matn qaytarishi mumkin** (kalit yo'q / provayder yiqilsa) — bu
   jimgina, xatosiz, "muvaffaqiyatli" javob sifatida (`success=True`), kredit yechilgan holda.
2. **`orchestrator.py:193` dagi `len(retry_output) >= 20` sharti validatorsiz matnni qabul qiladi** —
   runtime'da isbotlandi (til mos emas, xavfli teg, hatto Mock matni).
3. **`services/ai/*` bugungi kunda hech bir handler'ga ulanmagan** (faqat testlar import qiladi) — ya'ni Mock
   xavfi hozircha "yashirin", lekin **yangi funksiyalar aynan shu zanjirning birinchi production iste'molchisi
   bo'ladi**. Ya'ni xavf eski kodda emas, **keyingi qadamda**.

### 0.2. 5 ta yo'nalish bo'yicha verdict

| # | Yo'nalish | Holat | Asosiy xulosa |
|---|---|---|---|
| 1 | AI Provider Chain & Mock xavfi | 🔴 **KRITIK** | Mock production'da **enable/disable qilinmagan**, `ProviderChain` da 4-element sifatida doim turadi + zanjir oxirida majburiy 2-zaxira; `len>=20` bypass bor. |
| 2 | ENV & konfiguratsiya | 🟠 **O'rtacha** | 2 ta o'zgaruvchi **ikkita nusxada** (`GEMINI_VISION_MODEL`, `VISION_MAX_FILE_BYTES`), 1 tasi **eskirgan model** (`gemini-1.5-flash` — o'zi "o'chirilgan" deb yozilgan), 25 ta kod o'zgaruvchisi `.env.example` da **umuman yo'q**, ikki `.env.example` **sinxron emas**. |
| 3 | Health check & monitoring | 🟡 **Yaxshi, lekin bo'shliqlar bor** | `/health` (Telegram, RBAC) + 4 ta HTTP endpoint mavjud; DB/scheduler/AI-kalit/to'lov tekshiriladi. **Yo'q:** Telegram API probe, AI **jonli** probe, Mock ishlatilish metriкasi, admin uchun JSON/machine-readable endpoint. |
| 4 | DB & kanal owner modeli | 🟠 **Team access uchun tayyor emas, DNA uchun poydevor bor** | `channels.user_id` — yagona egasi, `UNIQUE(channel_id)` — kanal 1 userga. `channel_members`/`editors` jadvali yo'q. RBAC rollari **bot-admin** darajasida (owner/editor emas). DNA uchun faqat `tone_of_voice` (4 qiymat) bor. |
| 5 | Scheduler & reklama mezonlari | 🟢 **Yaxshi poydevor** | Auto-delete ✅ (24 soatlik post **allaqachon bor**), takroriy e'lon ✅ (daily/weekly), navbat slotlari ✅ (`queue_slots`). **Yo'q:** quiet hours, `ad_pool` da TTL/oyna/prioritet, engagement-asosidagi "best time", FREE navbat limiti 5 ta (7-kunlik autopilot uchun to'siq). |

### 0.3. Eng muhim 3 ta xulosa (qisqa)

* **P0-A:** `MockProvider` production'da **o'chirib bo'lmaydi** (env flag yo'q) va u xato bermaydi —
  `ProviderChain.execute()` har qanday holatda matn qaytaradi. Zanjirning bugungi iste'molchilari testlar
  bo'lgani uchun bu hozir foydalanuvchiga yetib bormaydi, **lekin Phase 1 da birinchi handler ulanishi bilan
  darhol P0 bo'ladi.**
* **P0-B:** `orchestrator.py:193` — 1 martalik retry natijasi **validatordan qat'i nazar** qabul qilinadi,
  agar uzunligi ≥ 20 bo'lsa. Runtime'da `LANGUAGE_MISMATCH` va `INVALID_CHARACTERS` holatlari qabul
  qilinishi isbotlandi (1.4-bo'lim).
* **P1-C:** `channels` jadvali "Team access" uchun qayta loyihalashni talab qiladi (yangi `channel_members`
  jadvali + barcha egalik tekshiruvlarini yagona helper'ga o'tkazish), aks holda Autopilot + DNA ni
  ko'p foydalanuvchili kanalda ishlatib bo'lmaydi.

---

## 1. AI PROVIDER CHAIN & MOCK XAVFI

### 1.1. Arxitektura: **ikkita mustaqil AI zanjiri mavjud**

| Zanjir | Fayl | Mock bormi? | Bugungi iste'molchilar |
|---|---|---|---|
| **A) `services/ai_service.py`** — `AIFallbackService` | `services/ai_service.py:501-628` | ❌ **Yo'q** — barcha provayderlar yiqilsa `_graceful_error()` qaytaradi (`ai_unavailable=True`, `quota_safe=True`) — `services/ai_service.py:449-499` | **BARCHA user-facing oqimlar**: Magic Post, AI Studio, Voice, Image, Post Score, kontent-reja (`utils/ai_agent.py`, `run_ai_chain`) |
| **B) `services/ai/*`** — `AIOrchestrator` + `ProviderChain` | `services/ai/providers.py`, `services/ai/orchestrator.py` | ✅ **HA** — `MockProvider` | **Faqat testlar** (10 test fayli) + `middlewares/fsm_cleaner.py:144` (`ai_concurrency_manager` — bekor qilish uchun, generatsiya emas) |

> **Muhim topilma:** `git grep "services.ai."` natijasi — Phase 11/12 "advanced SMM" qatlami
> (`variants.py`, `repurpose.py`, `audit.py`, `planner.py`, `smm_common.py`) **hech bir handler tomonidan
> import qilinmagan**. Ya'ni `MockProvider` bugun production foydalanuvchisiga **yetib bormaydi**.
> Bu xavfni **hozir arzon narxda yopish imkonini beradi** — lekin yangi funksiyalar (Channel DNA, Autopilot,
> RSS, Recycle) tabiiy ravishda `services.ai` zanjirini ishlatgani uchun birinchi production ulanish
> **P0 ga aylanadi**.

### 1.2. Mock "jimgina ishga tushish" zanjiri (aniq satrlar)

```
services/ai/providers.py
├─ 139-146  MockProvider(AIProvider) ; is_available() -> True            ← kalit talab qilmaydi
├─ 337-346  ProviderChain.__init__ — DEFAULT zanjir:
│              [GeminiProvider(), GroqProvider(), OpenRouterProvider(), MockProvider()]
│              → Mock HAR DOIM 4-element sifatida zanjirda turadi
├─ 356      if not provider.is_available() and not isinstance(provider, MockProvider): continue
│              → Mock "kalit yo'q" filtriga ham TUSHMAYDI
├─ 359-367  for provider in self.providers:  ...  return result.strip(), provider.name
│              → Mock natijasi "muvaffaqiyat" sifatida qaytariladi (provider_name="Mock")
└─ 369-373  # Zanjir tugagach, MAJBURIY ikkinchi Mock urinishi
             mock = MockProvider(); res = await mock.generate(prompt, context); return res, mock.name
             → hatto zanjirga Mock qo'shilmagan bo'lsa ham (custom providers) mock qaytariladi
```

**Himoya flag'i yo'q.** Butun repozitoriyda `ENVIRONMENT` / `PRODUCTION` / `DEBUG` / `AI_ALLOW_MOCK`
kabi muhit-detect **umuman mavjud emas** (`grep -rn "PRODUCTION\|ENVIRONMENT\|APP_ENV" telegram_bot/` — 0 natija).
Ya'ni production va test muhiti kod uchun **bir xil**.

### 1.3. Orchestrator tomonidagi Mock yo'llari

```
services/ai/orchestrator.py
├─ 175-176  val_res = self.validator.validate(raw, expected_lang=lang)     ← 1-urinish: TO'G'RI tekshiriladi
├─ 179-199  if not val_res.is_valid and val_res.needs_retry:
│              193:  if val_second.is_valid or len(retry_output) >= 20:    ← ⚠️ VALIDATOR BYPASS
│              197-199: mock = MockProvider(); raw = await mock.generate(prompt, ctx)
│                       provider = f"{retry_provider}+mock_safe"           ← foydalanuvchiga "Mock" ko'rinmaydi
└─ 200-204  except Exception: mock = MockProvider(); provider = "MockFallback"
```

**Muhim oqibatlar:**
* Mock matni **validator'dan o'tadi** (u uzun, to'g'ri tilda, HTML bilan) → `success=True`.
* Kvota **yechilgan holda qoladi** — `orchestrator.orchestrate()` `success=True` qaytaradi, refund yo'q
  (`orchestrator.py:232-242`); chaqiruvchi (`smm_common.ask`, `smm_common.py:576-590`) faqat uzunlikni
  tekshiradi, provayder nomini emas.
* `provider_used` **hech bir handler'da tekshirilmaydi** — `grep -rn "provider_used" telegram_bot/handlers/`
  → **0 natija**. Ya'ni Mock ishlatilgani **foydalanuvchiga ham, adminga ham ko'rinmaydi** (faqat log'da
  `logger.info("AI Provider chaqirilmoqda: Mock")`).

### 1.4. Runtime isbot (kod o'zgartirilmagan holda o'tkazilgan eksperimentlar)

Eksperiment `/tmp/venv` da (repo kodiga tegilmagan), AI kalitlari **butunlay olib tashlangan** holatda:

```
== 1) ProviderChain.execute (kalitlar yo'q = production kabi) ==
   zanjir:        ['Gemini 2.5 Flash', 'Groq', 'OpenRouter', 'Mock']
   availability:  [False, False, False, True]
   provider_used = Mock
   validate()    = ValidationResult(is_valid=True, error_code=None)      ← Mock matni "yaroqli"
   → AIOrchestrator.orchestrate(...): success = True | provider_used = Mock | error = None

== 2) Validator bypass (orchestrator.py:193) ==
   A) retry chiqishi 30 ta BO'SH JOY  → success=True (va Mock matni ichki retry-instruksiya bilan
                                        foydalanuvchi postига sizib chiqadi!)
   B) RU kutilgan, EN javob (32 belgi) → validate() = LANGUAGE_MISMATCH  →  success=True, matn qabul
   C) "<script>alert(1)</script>x"     → validate() = INVALID_CHARACTERS  →  success=True, matn qabul
```

* **(A)** — bo'sh/bo'shliqli retry natijasi `ProviderChain` tomonidan "yaroqsiz" deb tashlanadi
  (`providers.py:363` `if result and result.strip()`), so'ngra Mock ishga tushadi va **promptning o'zini**
  post matni sifatida qaytaradi. Natijada foydalanuvchi postida validator'ning ichki ko'rsatmasi ko'rinadi:
  `🔥 <b>test\n\n\nMUHIM: Oldingi javob juda qisqa yoki b...`. Bu — **internal prompt leakage + soxta kontent**.
* **(B)** — rus tilida so'ralgan post **inglizcha** qaytishi mumkin; `LANGUAGE_MISMATCH` e'tiborsiz qoladi.
* **(C)** — `INVALID_CHARACTERS` (xavfli teg) verdict'i e'tiborsiz qoladi; HTML sanitizer keyinroq escape
  qiladi (`orchestrator.py:226-230`), ya'ni XSS emas, **lekin foydalanuvchi axlat matn oladi va kredit yechiladi**.

### 1.5. "Mantiqsiz joylar" (so'ralgan tekshiruv) — to'liq ro'yxat

| Satr | Kod | Muammo | Daraja |
|---|---|---|---|
| `orchestrator.py:193` | `if val_second.is_valid or len(retry_output) >= 20:` | Validator verdict'i uzunlik bilan ustidan yoziladi (`len` HTML bilan birga, `is_valid=False` bo'lsa ham qabul) | 🔴 **P0** |
| `providers.py:369-373` | Zanjir tugagach majburiy Mock | Zanjir "yiqildi" signali yo'q; Mock = muvaffaqiyat | 🔴 **P0** |
| `providers.py:356` | `... and not isinstance(provider, MockProvider)` | Mock kalit-filtridan ozod | 🔴 **P0** |
| `providers.py:345` | default zanjirda `MockProvider()` | Env flag yo'q (`AI_ALLOW_MOCK=0` kabi) | 🔴 **P0** |
| `providers.py:144-145` | `MockProvider.is_available() -> True` | Har doim "mavjud" | 🟠 P1 |
| `orchestrator.py:197-199, 202-204` | `f"{retry_provider}+mock_safe"`, `"MockFallback"` | Provayder nomi chalkashtiriladi; metrika buziladi | 🟠 P1 |
| `smm_common.py:576-590` | `ok` faqat uzunlikka qarab | `provider == "Mock"` tekshiruvi yo'q | 🟠 P1 |
| `audit.py`/`variants.py`/`planner.py`/`repurpose.py` | Mock rejimida "100% yashil" deb **dizayn qilingan** | Test uchun to'g'ri, production uchun **xavfli default** | 🟠 P1 |
| Test kutishlari | `tests/ai_orchestrator_test.py:145-159` (`assert used == "Mock"`), `tests/ai_advanced_features_test.py` (5-band: "kalitsiz 100% yashil") | Mock'ni **ataylab** talab qiladi — tuzatish testlarni ham yangilashni talab qiladi | ℹ️ Eslatma |

### 1.6. Ijobiy tomonlar (bularni buzmaslik kerak)

* `services/ai_service.py` zanjiri **to'g'ri** ishlaydi: Mock yo'q, `_graceful_error` + `quota_safe=True` +
  circuit breaker (`utils/ai_agent.py:559-600`) — bu **andoza**, `services/ai/*` ni ham shunga keltirish kerak.
* Atomik kvota: `services/ai_quota.py` → `database.reserve_ai_request()` (bitta tranzaksiya, `FOR UPDATE`)
  va fail-closed refund (`orchestrator.py:244-298`).
* Concurrency: `services/ai/concurrency.py:29-88` (`MAX_AI_CONCURRENCY`, `MAX_AI_QUEUE`, `generation_id`,
  bekor qilish, idempotent refund) — Autopilot batch generatsiyasi uchun tayyor infratuzilma.
* Sanitizatsiya: `orchestrator.py:224-230` + `smm_common.render()` (ikki bosqichli sanitize + chunk).

---

## 2. ENV & KONFIGURATSIYA

### 2.1. Dublikatlar (so'ralgan tekshiruv) — tasdiqlandi

| O'zgaruvchi | `.env.example` (root) | `telegram_bot/.env.example` | Qiymatlar | Xavf |
|---|---|---|---|---|
| `GEMINI_VISION_MODEL` | **48-satr** va **92-satr** | **48-satr** va **92-satr** | 48: `gemini-1.5-flash` (eski) · 92: `gemini-2.5-flash` (yangi) | 🟠 Chalkashlik: faylni o'qigan odam/hodim 1.5 ni "amaldagi" deb o'ylaydi. Docker/python-dotenv'da **oxirgisi g'olib** (2.5), lekin Render Environment panelida o'zgaruvchilar birma-bir kiritilsa **birinchisi** yozilib qolish ehtimoli bor. |
| `VISION_MAX_FILE_BYTES` | **50-satr** va **89-satr** | **50-satr** va **89-satr** | ikkalasi ham `10485760` | 🟡 Zararsiz (bir xil qiymat), lekin "yagona manba" tamoyilini buzadi. |

Kod tomonida ziddiyat **haqiqiy**: `utils/ai_agent.py:3249` va `utils/vision_analyzer.py:49` **ikkalasi ham**
`GEMINI_VISION_MODEL` ni o'qiydi va default `gemini-2.5-flash` beradi — ya'ni kod **yangi** modelni to'g'ri
tanlaydi, faqat hujjat eski qiymatni ko'rsatib turadi.

### 2.2. Eskirgan ma'lumotlar (stale)

| Joy | Muammo |
|---|---|
| `.env.example:48` / `telegram_bot/.env.example:48` | `GEMINI_VISION_MODEL=gemini-1.5-flash` — **aynan shu faylning 91-satrida** "`gemini-1.5-flash` 2025-09-29 dan o'chirilgan" deb yozilgan. Ichki ziddiyat. |
| `.env.example:101` | `GEMINI_AUDIO_MODEL=gemini-1.5-flash` — Voice→Post **zaxira** (Gemini STT) yo'li o'chirilgan modelga ishora qiladi. Kod default'i ham eski: `utils/audio_transcriber.py:65`. Ya'ni `GROQ_API_KEY` ishlamasa, STT zaxirasi **ishlamaydi**. |
| `.env.example:13` | `DATABASE_URL=postgresql://user:password@host:5432/dbname` — faqat namuna; Render'da Neon pooler misoli yuqorida bor (12-satr) — qabul qilinadi, lekin production uchun `?sslmode=require` tavsiyasi faqat izohda. |
| `README.md` | **21 bayt** — amalda bo'sh. `telegram_bot/README.md` asosiy hujjat. Yangi funksiyalar uchun hujjat joyi yo'q. |

### 2.3. Ikki `.env.example` sinxron emas

`diff` natijasi (izohsiz qatorlar):

```
Root .env.example da BOR, telegram_bot/.env.example da YO'Q (5 ta):
    GROQ_STT_ENDPOINT, GROQ_STT_MODEL, GEMINI_AUDIO_MODEL,
    STT_CONNECT_TIMEOUT, STT_TOTAL_TIMEOUT
```

Ya'ni **Render (Root Directory = `telegram_bot`)** uchun ishlatiladigan nusxada butun **🎙 VOICE→POST / STT**
bo'limi yo'q — bu funksiyaning env sozlamalari hujjatlashtirilmagan (`POST_SCORE_*` bo'limi esa joyi
o'zgargan holda ikkalasida ham bor).

### 2.4. Kodda ishlatiladi, lekin **hech bir** `.env.example` da yo'q (25 ta)

| Guruh | O'zgaruvchilar | Nima uchun muhim |
|---|---|---|
| AI navbat/limit | `MAX_AI_CONCURRENCY`, `MAX_AI_QUEUE`, `AI_QUEUE_TIMEOUT` | `services/ai/concurrency.py:30-32` — Autopilot batch'i shu navbatdan o'tadi. Hujjatda yo'q → tuning qilish qiyin. |
| AI timeout/darajalar | `AI_HARD_TIMEOUT`, `AI_TOTAL_TIMEOUT`, `AI_PRO_TWO_STAGE`, `AI_PRO_AUDIT_TIMEOUT` | `utils/ai_agent.py` (PRO 2-bosqichli audit). |
| Model discovery | `GEMINI_MODELS_ENDPOINT`, `GROQ_MODELS_ENDPOINT`, `OPENROUTER_MODELS_ENDPOINT`, `OPENROUTER_FREE_ROUTER_MODEL` | `utils/ai_agent.py:449` va h.k. |
| Fallback flag | **`ENABLE_POLLINATIONS_FALLBACK`** | `services/ai_service.py:139-141` — kalitsiz fallback. **Xavfsizlik uchun muhim flag hujjatda yo'q!** |
| Kalit | `GOOGLE_API_KEY` | `services/ai/providers.py:45` (`GEMINI_API_KEY` muqobili). |
| Tarif/limitlar | `FREE_MAX_CHANNELS`, `FREE_DAILY_AI`, `PRO_MAX_CHANNELS`, `PRO_DAILY_AI` | `config.py:114-117` → Autopilot entitlement'ini shu yerdan qo'shish tabiiy. |
| Narx | `STARS_PRICE_1M/3M/1Y`, `USD_EQUIV_1M/3M/1Y` | `config.py:107-112`. |
| RBAC | `RBAC_CACHE_TTL`, `RBAC_DB_TIMEOUT` | `services/rbac_service.py` — admin/team ruxsatlari uchun. |

> **Izoh:** `CLEANUP_*`, `SHUTDOWN_GRACE_SECONDS`, `HEALTH_*` kabi 10 ta o'zgaruvchi **`.env.example` da e'lon
> qilingan va kodda `os.getenv` bilan dinamik o'qiladi** (masalan `_env_int("HEALTH_FAILED_ALERT", 10)`) —
> ular to'g'ri, ro'yxatga kirmaydi.

### 2.5. Xulosa va tavsiya (kod o'zgartirmasdan)

1. Ikkala `.env.example` ni **bitta manbadan generatsiya qilish** (yoki ikkinchisini birinchisiga symlink/ssg
   qilish) — chetlanishni butunlay yo'q qiladi.
2. `GEMINI_VISION_MODEL` ni **bitta joyda** qoldirish (92-satr, `gemini-2.5-flash`), 48-satrni o'chirish.
3. `GEMINI_AUDIO_MODEL` → `gemini-2.5-flash` (yoki `gemini-2.0-flash`), `audio_transcriber.py:65` default'i ham.
4. `ENABLE_POLLINATIONS_FALLBACK=0` va yangi `AI_ALLOW_MOCK=0` ni **majburiy hujjatlashtirish**.
5. Yangi funksiyalar uchun `AUTOPILOT_*`, `CHANNEL_DNA_*` bo'limlarini qo'shishda **ikki faylga ham** yozish.

---

## 3. HEALTH CHECK & MONITORING

### 3.1. Mavjud mexanizmlar (bor)

| Qatlam | Joy | Nima qiladi | Himoya |
|---|---|---|---|
| **Telegram buyruq** | `handlers/health.py:31-49`; ro'yxatga olish `handlers/__init__.py:1560` | `/health` → to'liq HTML hisobot, foydalanuvchi tilida (uz/ru/en) | `@require_permission(PERM_SYSTEM_SETTINGS)` → **faqat OWNER** (`rbac_service.py:96-105`) |
| **Servis** | `services/health_service.py:462-500` (`get_system_health`) | DB + scheduler + AI provayderlar + to'lovlar + tizim | Har komponent alohida `try/except`, hech qachon istisno ko'tarmaydi |
| **HTTP endpointlar** | `utils/web_server.py:15-45` | `GET /`, `/health`, `/health/live` → liveness (doim 200); `GET /health/ready` → DB ping (503 yoki 200) | **Autentifikatsiyasiz** (aiohttp, ochiq port) |
| **Docker** | `Dockerfile` HEALTHCHECK + `docker-compose.yml` healthcheck | `get_system_health()` ni alohida jarayonda chaqiradi; faqat `UNHEALTHY` da nosog'lom | Alohida jarayon → scheduler `UNKNOWN` bo'ladi (bu **DEGRADED**, healthcheck `exit 0`) |
| **Xato statistikasi** | `handlers/error_handler.py` (`get_error_stats`) → `health_service.py:394-421` | oxirgi 1 soat / 24 soat xatolar | — |

### 3.2. Komponent tekshiruvlari (aniq)

| Komponent | Joy | Usul | Holatlar |
|---|---|---|---|
| Database | `health_service.py:167-194` | `db.ping_db_with_latency` + `db.get_db_pool_status` (thread'da) | `OK` / `UNHEALTHY` |
| Scheduler | `health_service.py:200-236` + `db.get_post_health_counts` | `scheduler.running`, `len(get_jobs())`, pending/processing/failed/stale/dead_letter/unknown | `RUNNING` / `STOPPED` / `UNKNOWN` |
| **AI provayderlar** | `health_service.py:305-388` | **kalit borligi** (`provider.is_available()`) + **circuit-breaker** holati (`ai_agent._breaker_open`) | `OK` / `DEGRADED` (breaker ochiq) / `UNCONFIGURED` (kalit yo'q) |
| To'lovlar | `health_service.py:256-290` | `db.get_payments_health_counts` + karta/Stars konfiguratsiyasi | `OK` / `DEGRADED` / `DISABLED` / `UNKNOWN` |
| Umumiy | `health_service.py:428-459` | DB yiqilsa → `UNHEALTHY`; aks holda sabablarga qarab `DEGRADED`/`HEALTHY` | — |

### 3.3. Bo'shliqlar (yangi funksiyalar uchun muhim)

| # | Bo'shliq | Dalil | Yangi funksiyaga ta'siri |
|---|---|---|---|
| 1 | **Telegram API probe yo'q** | `health_service.py` da `get_me`/`getMe` **yo'q** (grep 0) | Autopilot "kanalga chiqyaptimi?" savoliga javob yo'q; bot token o'lik bo'lsa `/health` baribir `HEALTHY` |
| 2 | **AI jonli probe yo'q** | `_check_ai_providers` faqat `is_available()` (kalit satri) + breaker o'qiydi | Kalit bor, lekin 401/429 — `/health` `OK` deydi. Autopilot generatsiya qila olmasligi oldindan ko'rinmaydi |
| 3 | **Mock ishlatilish metriкasi yo'q** | `provider_used` DB'ga yozilmaydi; in-memory counter ham yo'q | 1-bo'limdagi xavfni **monitoringsiz** qoldiradi |
| 4 | **AI navbat holati yo'q** | `concurrency.py:64-88` (`_active_slots`, `_waiting_count`) health'ga uzatilmagan | Autopilot batch'i navbatni to'ldirsa (MAX_AI_QUEUE=20) `/health` ko'rsatmaydi |
| 5 | **Machine-readable endpoint yo'q** | HTTP `200 {"status":"ok"}` — tafsilotsiz; to'liq hisobot faqat Telegram matni | Tashqi uptime monitoring (UptimeRobot kabi) faqat "jarayon tirik" ni biladi |
| 6 | **Autopilot/RSS job sog'lig'i** | Job ro'yxati `main.py:443-476` — kelajakdagi joblar uchun "oxirgi muvaffaqiyatli run" kuzatuvi yo'q | "Autopilot 3 kundan beri ishlamayapti" holatini aniqlab bo'lmaydi |
| 7 | **Kanal-darajasidagi salomatlik yo'q** | `scheduler` bo'limi global pending/failed; kanal kesimida emas (`health_service.py:200-217`) | 1 ta kanal buzilib (bot chiqarib yuborilgan) qolsa, umumiy ko'rsatkichda ko'rinmaydi |

### 3.4. Tavsiya (Phase 1 uchun, kod hozircha tegmaydi)

* `/health` Telegram hisobotiga **"🎛 AI zanjiri"** qatorini qo'shish: `Mock ishlatilgan so'rovlar (24h)`,
  `jonli probe natijasi`, `navbat (active/waiting/queue_full)`.
* `GET /health/ready` ni kengaytirish: `?detail=1` bilan JSON (DB latency, scheduler, AI kalitlari,
  **mock_used_24h**) — faqat `HEALTH_TOKEN` header bilan (yangi env).
* Yangi funksiyalar (RSS ingest, Autopilot) uchun **"heartbeat"** yozuvi: `system_settings` da
  `job:autopilot:last_ok_at` — `/health` shu qiymatni ko'rsatadi.

---

## 4. DATABASE & KANAL OWNER MODELI

### 4.1. `channels` jadvali — bugungi holat (schema.sql:37-44)

```sql
CREATE TABLE IF NOT EXISTS channels (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,              -- ⚠️ yagona egasi (owner)
    channel_id VARCHAR(255) UNIQUE NOT NULL,  -- ⚠️ 1 kanal = 1 yozuv = 1 user
    channel_title VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- + keyingi bosqichda qo'shilgan:
ALTER TABLE channels ADD COLUMN IF NOT EXISTS tone_of_voice VARCHAR(30) DEFAULT 'friendly';
--   (schema.sql:416, database.py:1591, VALID_TONES = ("formal","friendly","concise","engaging") database.py:3066)
```

**Egalik mantig'i:** `database.py:2973-3020` (`save_channel`) — `ON CONFLICT (channel_id) DO UPDATE`:
faol kanalni boshqa user **tortib ololmaydi** (`(False, "taken")`); admin qayta biriktirsa egasi almashadi.
`UNIQUE(channel_id)` tufayli **bitta kanal bir vaqtda faqat bitta userga** tegishli bo'lishi mumkin.

### 4.2. "Team access (Owner / Editor)" uchun tayyorlik: ❌ **tayyor emas**

| Talab | Mavjud holat | Kerak bo'ladigan ish |
|---|---|---|
| Bir kanalga bir necha foydalanuvchi | `UNIQUE(channel_id)` + `channels.user_id` — **faqat 1 ta** | Yangi `channel_members (channel_id, user_id, role, granted_by, granted_at)` jadvali + `UNIQUE(channel_id, user_id)` |
| Owner/Editor rollari | `rbac_service.py:68-105` rollari **bot-admin** uchun: `OWNER`, `SUPER_ADMIN`, `ADMIN`, `MODERATOR`, `FINANCE`, `USER` — kanal kontekstida emas | Kanal-darajasidagi `role` maydoni (`owner`/`editor`/`viewer`) — mavjud RBAC'ga **aralashtirmaslik** kerak |
| Ruxsat tekshiruvi | Har handler o'zi qiladi, masalan `handlers/channels.py:898-910` (`owned = any(...)`) va `db.get_user_channels_with_tone(user_id)` | Yagona helper: `db.user_can_edit_channel(user_id, channel_id) -> bool` + barcha joyda shunga o'tish (`channels.py`, `new_post.py`, `queue.py`, `content_plan.py`, `manual_post.py`, `channel_extract.py`) |
| Audit | `admin_audit_logs` (schema.sql:290-301) faqat **bot-admin** amallari uchun | Kanal-darajasidagi audit (kim DNA'ni o'zgartirdi, kim autopilotni yoqdi) — mavjud jadvalga `target_type='channel'` bilan yozish mumkin ✅ |
| Kesh | `get_user_channels` (`database.py:2929-2942`) `DB_USER_CACHE_TTL` bilan keshlaydi va `_invalidate_user()` chaqiriladi | A'zolar o'zgarganda **yana bir user** keshi ham invalidatsiya qilinishi kerak (hozir bu naqsh `save_channel` da bor — `database.py:3013-3016`) |

> **Xulosa:** Team access — **yangi jadval + egalik tekshiruvlarini markazlashtirish** ishini talab qiladi.
> Bu ish Autopilot va DNA'dan **oldin** bajarilishi kerak, aks holda keyinchalik har bir handler'ni qayta
> yozishga to'g'ri keladi.

### 4.3. "Channel DNA" uchun tayyorlik: 🟡 **qisman (poydevor bor)**

**Bor:**
| Element | Joy | Izoh |
|---|---|---|
| Uslub profili | `channels.tone_of_voice` (`schema.sql:416`) | 4 ta qiymat: formal/friendly/concise/engaging (`database.py:3066-3098`) |
| Kanal postlari tarixi | `channel_posts_history` (`schema.sql:193-203`) | `channel_id, message_id, content, views, post_date` + indeks `(channel_id, post_date DESC)` |
| Tarixni to'ldirish | `handlers/channels.py:988-1025` (`on_channel_post`) | Bot admin bo'lgan kanallardagi **har bir yangi post** avtomatik yoziladi (edit'da `views` yangilanadi — `database.py:5648-5695`) |
| Tarixni o'qish | `db.get_channel_posts_history(channel_id, limit)` (`database.py:5700`) | AI tahlil uchun tayyor |
| **AI asosidagi "kanal ovozi" tahlili** | `handlers/channels.py:868-981` (`channel_voice_analysis_callback`) | So'nggi 15 postni AI bilan tahlil qiladi, natijani **faqat `tone_of_voice` ga** yozadi (4 ta qiymatga siqadi) |
| Ochiq kanaldan fallback | `utils/channel_reader.py:331-483` (`read_channel_posts`, `fetch_latest_channel_posts`) | Bot admin bo'lmagan kanallar uchun `t.me/s/<username>` scraping (post+views) |

**Yo'q (DNA uchun zarur):**
* Strukturaviy profil saqlanadigan joy: auditoriya, mavzular, tonallik aralashmasi, taqiqlangan so'zlar,
  CTA uslubi, hook namunalari, hashtag siyosati, "post kadansi" (format).
* `channel_posts_history` da **media turi** va **engagement poydevori** yo'q (`views` bor, reaksiyalar yo'q;
  `post_reactions` jadvali — `schema.sql:151-158` — **botning o'z tugmalari** uchun, kanal postlari uchun emas).
* Bir nechta kanal uchun **umumiy DNA** (brend darajasi) tushunchasi yo'q.

**Migratsiya yo'li (xavfsiz):** yangi jadval `channel_dna (channel_id UNIQUE FK, ... JSONB)` **yoki**
`channels` ga `dna JSONB` ustuni. `schema.sql` + `database.py:1564-1646` (`migrations` ro'yxati,
har biri SAVEPOINT bilan, `ADD COLUMN IF NOT EXISTS`) naqshiga to'liq mos — **mavjud ma'lumotga zarar yo'q**.

### 4.4. Migratsiya mexanizmi (muhim texnik fakt)

* `schema.sql` bot har ishga tushganda `_init_db_once()` orqali **avtomatik bajariladi** (`schema.sql:4-7`),
  barcha operatorlar idempotent.
* Qo'shimcha `migrations` ro'yxati — `database.py:1564-1646`: har bir statement alohida `SAVEPOINT` bilan,
  xato bo'lsa `ROLLBACK TO SAVEPOINT` + `logger.warning` → **bitta xato qolganlarini to'xtatmaydi**.
* Constraintlar `NOT VALID` + keyin `validate_integrity_constraints()` (`schema.sql:488-596`,
  `DB_VALIDATE_INTEGRITY` env) — eski ma'lumot buzilmaydi.
* ⚠️ **Versiyalash jadvali yo'q** (`schema_migrations` kabi) — yangi jadval qo'shishda tartib/izohlar
  intizomi muhim.
* ⚠️ `users.role` va `admin_roles` **mavjud ikkita rol manbasi** (`database.py:5804-5941`) —
  kanal-darajasidagi rollarni bu yerga **qo'shmaslik** kerak (chalkashlik).

### 4.5. Autopilot uchun DB bo'shliqlari

| Kerak | Mavjud | Izoh |
|---|---|---|
| Post qaysi tizim tomonidan yaratilgani (autopilot/RSS/recycle) | ❌ `scheduled_posts` da `origin`/`source` ustuni yo'q | Kerak: `origin VARCHAR(32)` (`manual`/`magic`/`autopilot`/`rss`/`recycle`) — statistik, kvota va "o'chirish" uchun |
| Autopilot konfiguratsiyasi (kanal, kunlik rejim, davomiylik, holat) | ❌ jadval yo'q | Kerak: `channel_autopilot (channel_id, user_id, enabled, posts_per_day, slots, start_date, end_date, plan_source, last_run_at, ...)` |
| Generatsiya tarixi/takrorlanishning oldini olish | 🟡 `scheduled_posts.user_post_number` bor | Autopilot uchun `generation_id`/`topic_hash` (dublikat post oldini olish) kerak |
| FREE foydalanuvchi navbat limiti | ✅ `FREE_QUEUE_MAX_POSTS = 5` (`database.py:4492`, `check_queue_limit` 5170-5189) | ⚠️ **7 kunlik autopilot = 7 post** → FREE uchun **darhol limitdan oshadi**. Limitni qayta ko'rib chiqish yoki Autopilot postlarini alohida hisoblash kerak |

---

## 5. SCHEDULER & REKLAMA MEZONLARI

### 5.1. Joblar ro'yxati (`main.py:439-476`)

| Job | Trigger | Joy |
|---|---|---|
| `check_and_send_posts` | `interval 1 daqiqa` (birinchi tick darhol) | `main.py:443-448` → `scheduler.py:821-893` |
| `check_and_delete_expired_posts` | `interval 1 daqiqa` | `main.py:449-454` → `scheduler.py:1315-1354` |
| `cleanup_old_data` | `cron */6 soat` | `main.py:455-459` |
| `subscription_sweep` | `interval 15 daqiqa` | `main.py:460-466` → `database.downgrade_expired_subscriptions` |
| `cleanup_old_records` | `cron 03:00` (`CLEANUP_CRON_*`) | `main.py:467-476` → `services/cleanup_service.py` |

Joblar standartlari: `max_instances=1`, `coalesce=True`, `misfire_grace_time=300..6h`,
`timezone=Asia/Tashkent` (`main.py:439-476`).

**Navbat olish (yagona ishonchli nuqta):** `db.get_due_posts(now)` — `database.py:3594-3619`:
`UPDATE ... WHERE status='pending' AND scheduled_time <= now ORDER BY scheduled_time LIMIT POST_BATCH_SIZE
FOR UPDATE SKIP LOCKED` → atomik claim (parallel schedulerlar dublikat chiqarmaydi).

**Idempotentlik:** `post_deliveries` (`schema.sql:130-149`) + `SchedulerService`
(`services/scheduler_service.py:189-452`): `claim → processing → sent / failed(backoff 30s,2m,5m,15m) /
dead_letter(5 urinish) / unknown`. Restart recovery: `scheduler.py:1374-1396`.

### 5.2. Auto-delete — ✅ **bor va ishlaydi**

| Element | Joy |
|---|---|
| Ustun | `scheduled_posts.delete_after_hours INT DEFAULT 0` (`schema.sql:107`, migratsiya `schema.sql:405`) |
| Rejalashtirilgan o'chirish yozuvi | `sent_post_messages (delete_at, deleted_at)` (`schema.sql:161-168`) |
| Worker | `scheduler.py:1315-1354` — transient/forbidden/gone klassifikatsiyasi (`classify_delete_error` `scheduler.py:469-501`), retry `AUTO_DELETE_RETRY_DELAY=300s` |
| **"24 soatlik e'lon"** | **ALLAQACHON BOR**: `handlers/manual_post.py:19-21, 203` (`MODE_24H` → `delete_after_hours=24`), UI tugmasi `🗑 24 soatlik e'lon` |
| Umumiy tanlov | `handlers/new_post.py:1433` (`delete_after_hours`), ko'rsatish `queue.py:384-385`, preview `new_post.py:719-720` |

> Ya'ni **yangi "24 soatlik e'lon" turini reklama puli (`ad_pool`) uchun** qo'shish kerak — foydalanuvchi
> postlari uchun bu allaqachon mavjud.

### 5.3. Takroriy e'lon (recurrence) — ✅ **bor (daily/weekly)**

| Element | Joy |
|---|---|
| Ustunlar | `recurrence_type/day/time`, `end_date` (`schema.sql:112-115`) |
| Hisoblash | `calculate_next_time()` — `scheduler.py:503-528` (**faqat `daily` va `weekly`**; boshqasi → `None`) |
| Qayta rejalashtirish | `scheduler.py:194-199` (`_apply_sent_marker` ichida: `end_date` tekshiriladi → `pending` yoki `completed`) |
| UI | `handlers/manual_post.py:204-217` (`🔄 Takroriy e'lon` → `recurrence_type='daily'`) |
| Testlar | `telegram_bot/tests/unit_test.py:37-64` |

**Kengaytirish kerak bo'ladigan joylar:** `monthly`, "har N kunda", "haftada N marta", `recurrence_count`
(necha marta takrorlash) — hozir `end_date` bor, lekin `recurrence_type` enum'i tor.

### 5.4. **Quiet hours — ❌ YO'Q (umuman)**

`grep -rn "quiet" telegram_bot/` → faqat 2 ta aloqasiz natija (`smm_mock.py:95` "quietly" so'zi,
`translations/voice_post.py:299` "quiet place"). Ya'ni:

* Qora ro'yxat/ruxsat etilgan soatlar tushunchasi yo'q;
* `get_due_posts` (SQL) va `_execute_send` (Python) da vaqt filtri yo'q — post **aynan belgilangan vaqtda**
  chiqadi, hatto tunda bo'lsa ham.

**Xavfsiz integratsiya nuqtalari (muhim):**
| Variant | Joy | Plyus/minus |
|---|---|---|
| **(A) SQL filtr** — `get_due_posts` da `AND (scheduled_time AT TIME ZONE 'Asia/Tashkent')::time NOT BETWEEN quiet_start AND quiet_end` | `database.py:3594-3619` | Navbat umuman olinmaydi. ➖ "ertaga ertalab chiqadi"ga ko'chirish kerak bo'ladi, aks holda post **kechikib** qoladi (`status='pending'` saqlanadi — bu xavfsiz, chunki tick har daqiqa). |
| **(B) Python filtr** — `_execute_send` boshida | `scheduler.py:1008-1035` | ➖ Idempotency kaliti `post_id+channel_id+scheduled_time` — vaqtni o'zgartirmasdan faqat kechiktirish mumkin (`db.retry_post`), bu **xavfsiz**; lekin claim allaqachon olingan bo'ladi (`mark_post_processing` + `claim_post_delivery`) → ehtiyotkorlik bilan `retry_post` orqali qaytarish kerak. |
| **(C) `scheduled_time` ni ko'chirish (reschedule)** | yangi helper | ✅ Eng toza: post **boshqa slotga** (masalan keyingi 09:00) ko'chiriladi; Autopilot keyinchalik shu mantiqni ishlatadi. ➖ `pending` postning vaqtini o'zgartirish — qabul qilinadigan (hali `post_deliveries` yozuvi yaratilmagan bo'lsa). |

> **Tavsiya:** quiet hours ni **kanal darajasida** (`channel_autopilot`/`channels` sozlamasi) saqlash va
> **(C) reschedule** yondashuvidan foydalanish — chunki Autopilot ham slotga joylashtirishni talab qiladi.

### 5.5. Reklama (ads) mexanizmi va yangi e'lon turlari

**Mavjud:**
| Element | Joy |
|---|---|
| Reklama puli | `ad_pool` (`schema.sql:71-81`): `scope` (`channel`\|`reply`), `text`, `button_text`, `button_url`, `is_active` |
| Konstantalar | `db.AD_SCOPE_CHANNEL`, `db.AD_SCOPE_REPLY` (`database.py`), `get_ads_full` |
| Rotatsiya | Round-robin (in-memory) — `utils/helpers.py:150-181` (`_next_ad_full`, `get_channel_ad_next_full_async`) |
| Chastota (mezon) | Har **N-postda**: `channel_post_counters` (`schema.sql:86-94`) + `should_show_channel_ad(post_count, interval)` (`helpers.py:133-147`), interval `db.get_channel_ad_interval()` |
| Postga qo'shish | `scheduler.resolve_channel_ad()` (`scheduler.py:771-820`) + `compose_post_text` (`scheduler.py:560+`) + `build_ad_button_row` (`scheduler.py:756-770`) |
| PRO yashirish | `ad_free_posts` / `ad_free_active` (`schema.sql:383-385`), `db.is_premium`, `has_ad_free` (`scheduler.py:1096-1105`) |
| Admin UI | `adp:` callback'lari (`handlers/admin.py`), `ad_pool_callback` (`handlers/__init__.py:1630`) |

**Yo'q:**
| Kerak | Holat |
|---|---|
| Reklama uchun **vaqt oynasi** (`start_at`/`end_at`, "faqat 18:00–22:00") | ❌ `ad_pool` da bunday ustunlar yo'q (faqat `is_active`) |
| **"24 soatlik reklama"** (chiqqach o'zi o'chadigan e'lon) | ❌ `ad_pool` da TTL yo'q; `channel_post_counters` faqat sanaydi. ➖ Lekin **post** darajasida `delete_after_hours` bor → reklama postini alohida `scheduled_posts` yozuvi sifatida yuborish bilan **qayta ishlatish mumkin** |
| **Prioritet / vazn** (A reklama 70%, B 30%) | ❌ faqat teng round-robin |
| **Namoyish statistikasi** (nechta kanalga chiqdi, nechta ko'rildi) | ❌ `ad_pool` da counter yo'q; `channel_post_counters.ad_count` global |
| Kuniga maksimal namoyish (frequency cap) | ❌ |
| Reklama turlari bo'yicha A/B test | ❌ |

> **Xulosa:** "yangi e'lon turlari (24 soatlik, takroriy)" **foydalanuvchi postlari uchun allaqachon bor**;
> **`ad_pool` (bot reklamasi) uchun esa** `ad_pool` ga `start_at`, `end_at`, `delete_after_hours`,
> `weight`, `impression_count` ustunlari + `find_next_ad` da filtr kerak bo'ladi.

### 5.6. **Smart Best Time** uchun mavjud poydevor

| Element | Joy | Izoh |
|---|---|---|
| Navbat "slotlari" (foydalanuvchi tanlagan soatlar) | `db.get_queue_slots/set_queue_slots` — `database.py:3930-3955`; `DEFAULT_QUEUE_SLOTS = ["09:00","14:00","19:00"]` | Saqlash: `system_settings` kaliti `queue_slots:{user_id}` (JSON) — ⚠️ `system_settings` global jadval, kalit bo'yicha ajratilgan (toza yechim emas, lekin ishlaydi) |
| Bo'sh slotni topish | `db.find_next_queue_slot(slots, occupied, now, max_days=7)` — `database.py:3977-4021` | "Bugun/Ertaga/DD.MM.YYYY" label bilan |
| Band vaqtlar | `db.get_queue_occupied_times(user_id, channel_id, date)` — `database.py:3958-3974` | Toshkent TZ'da (`AT TIME ZONE 'Asia/Tashkent'`) ✅ |
| UI | `handlers/queue.py:566-686` (`qslots:` — ko'rish/qo'shish/o'chirish/reset, maks. 10 slot) | To'liq tayyor |
| Statistika "peak hours" | `db.get_channel_post_stats` — `database.py:4203-4211` (`EXTRACT(HOUR FROM sp.scheduled_time)`) | ⚠️ **Bu eng ko'p POST QILGAN soat**, **eng ko'p KO'RILGAN soat emas** — ya'ni "smart" emas |
| Ko'rishlar (views) | `channel_posts_history.views` (`schema.sql:198`), yozilishi `handlers/channels.py:997-1024` | ✅ Mavjud, lekin **soat bo'yicha engagement agregatsiyasi yo'q** |
| Analitika UI | `handlers/analytics.py:116-161` (`an_dash_peak`) | Hozir "peak" = o'z postlari soni bo'yicha |

> **Xulosa:** Smart Best Time uchun **infratuzilmaning ~60% bor** (slotlar, band vaqtlar, UI).
> Yetishmaydi: (1) `channel_posts_history` dan **soat → o'rtacha views** agregatsiyasi, (2) natijani
> "tavsiya etilgan slotlar"ga aylantirish, (3) `queue_slots` ni `system_settings` dan **normallashtirilgan
> jadvalga** ko'chirish (kanal bo'yicha), (4) Toshkent TZ chegarasi (`EXTRACT(HOUR ... )` da TZ ko'rsatilmagan —
> `database.py:4205`; to'g'ri shakli `AT TIME ZONE 'Asia/Tashkent'`, xuddi `get_queue_occupied_times` dagidek).

---

## 6. YANGI FUNKSIYALAR UCHUN TAYYORGARLIK MATRITSASI

| Funksiya | Mavjud qurilish bloklari (fayl:satr) | Yetishmaydi | Tayyorlik |
|---|---|---|---|
| **Channel DNA** | `channels.tone_of_voice` (schema.sql:416), `channel_posts_history` (schema.sql:193-203), `on_channel_post` yozuvi (channels.py:988-1025), AI tahlil namunasi (channels.py:868-981), ochiq kanal fallback (channel_reader.py:331-483) | Strukturaviy DNA saqlash joyi (jadval/JSONB), media turi, engagement signali, DNA'ni generatsiyaga **majburiy** uzatish mexanizmi, DNA versiyalash | 🟡 **55%** |
| **7-Day Autopilot** | `db.schedule_week_posts()` — **7 kunlik kontentni bitta tranzaksiyada navbatga qo'yadi** (database.py:3175-3240), kontent-reja generatori (`services/ai/planner.py`, `utils/ai_agent.generate_content_plan`), slotlar (database.py:3930-3955), delivery idempotentligi, AI concurrency+queue | `channel_autopilot` jadvali, `scheduled_posts.origin`, to'ldirish (refill) jobi, quiet hours, **FREE navbat limiti (5 ta) to'sqinlik qiladi**, xato/token xarajati byudjeti | 🟡 **50%** |
| **Smart Best Time** | Slotlar + `find_next_queue_slot` + `get_queue_occupied_times` + UI (queue.py:566-686), views ma'lumoti | Soat→engagement agregatsiyasi, tavsiya algoritmi, slotlarni kanal darajasida normallashtirish, TZ xatosi (database.py:4205) | 🟢 **60%** |
| **URL → Post** | `utils/channel_reader.py:166-192` (`is_website_link`), `:507-591` (`read_webpage_for_ai` — URL'dan matn), `:306-330` (`_fetch_html`), `handlers/channel_extract.py:89+` (`_handle_website_link` oqimi bor!), AI rewrite (magic_post/uslub) | HTML → matn sifatini oshirish, `robots.txt`/etika, SSRF himoyasi (URL validatsiyasi!), media (rasm) olib kelish, manba attribution | 🟢 **65%** |
| **RSS** | **Hech narsa yo'q** — `grep -rni "\brss\b\|feedparser" telegram_bot/` → 0 natija | Yangi modul: feed parser (stdlib `xml.etree` bilan ham mumkin), `feed_sources` jadvali, dedupe (`guid`/`hash`), ingest job, media, AI rewrite + moderation, huquqiy ogohlantirish | 🔴 **5%** |
| **Content Recycle** | `channel_posts_history` (matn + views), `scheduled_posts` tarixi, `db.get_channel_posts_history` / `get_recent_posts` / `get_channel_post_stats`, `repurpose.py` (5 platforma uchun qayta ishlash — **test-only**), post_score heuristikasi | "Eng yaxshi post"ni tanlash mezonlari (views/reaksiyalar), takrorlanishga qarshi hash, "necha kundan keyin takrorlash mumkin" siyosati, qayta ishlash tarixi | 🟡 **45%** |

---

## 7. XAVFLAR REYESTRI (RISK REGISTER)

### 🔴 P0 — Yangi funksiyalarni ulashdan **OLDIN** yopilishi shart

| ID | Xavf | Joy | Ta'sir | Chora (Phase 1) |
|---|---|---|---|---|
| **P0-A** | `MockProvider` production'da "muvaffaqiyatli javob" sifatida ishlaydi; env flag yo'q | `providers.py:139-146, 337-373` | Foydalanuvchi soxta kontent oladi, **kredit yechiladi**, admin buni bilmaydi | `AI_ALLOW_MOCK` (default `0`) + `is_available()` da tekshirish + zanjir tugaganda **`AIProviderError`/`ai_unavailable` qaytarish** (Mock faqat explicit flag bilan) |
| **P0-B** | `len(retry_output) >= 20` validatorsiz matnni qabul qiladi | `orchestrator.py:193` | Til mos emas / xavfli / mazmunsiz matn foydalanuvchiga chiqadi; `INVALID_CHARACTERS` e'tiborsiz | Shartni olib tashlash: `if val_second.is_valid:` (aks holda Mock/passthrough emas, `error_code` bilan qaytarish) |
| **P0-C** | Mock matni **retry-instruksiyasi bilan** foydalanuvchi postiga sizib chiqadi | `providers.py:139-336` (Mock promptni `<b>{clean_prompt}</b>` ga qo'yadi) + `orchestrator.py:186, 198` | Ichki prompt leakage, "post" o'rniga ko'rsatma matni | Prompt sanitizatsiyasi: Mock prompt emas, **`ctx` maydonlarini** ishlatishi kerak; ichki ADDON matnini postdan olib tashlash |
| **P0-D** | Yangi funksiyalar `services/ai/*` ni production'da birinchi bo'lib ishlatadi (hozir faqat testlar) | `grep "services.ai."` → handler'larda 0 | Mock/validator muammolari **to'g'ridan-to'g'ri foydalanuvchiga** chiqadi | Yangi handler'lardan oldin P0-A/B/C ni yopish + `provider_used` ni **majburiy log/metric** qilish |

### 🟠 P1 — Phase 1 davomida

| ID | Xavf | Joy |
|---|---|---|
| P1-E | `channels.user_id` yagona owner + `UNIQUE(channel_id)` → Team access (Owner/Editor) imkonsiz | `schema.sql:37-44`, `database.py:2973-3020` |
| P1-F | Egalik tekshiruvi har handler'da takrorlanadi (markazlashmagan) → Team access'da **ruxsatsiz kirish** xavfi | `handlers/channels.py:898-910` va boshqa 6+ handler |
| P1-G | FREE navbat limiti 5 → 7-kunlik autopilot FREE'da ishlamaydi | `database.py:4492, 5170-5189` |
| P1-H | Quiet hours yo'q → tunda post chiqadi | `database.py:3594-3619`, `scheduler.py:1008-1035` |
| P1-I | `GEMINI_AUDIO_MODEL=gemini-1.5-flash` (o'chirilgan model) — Voice zaxirasi ishlamaydi | `.env.example:101`, `utils/audio_transcriber.py:65` |
| P1-J | `ad_pool` da vaqt oynasi/TTL/prioritet yo'q → "24 soatlik/takroriy" reklama turlari uchun yetarli emas | `schema.sql:71-81` |
| P1-K | `peak_hours` TZ'siz (`EXTRACT(HOUR FROM scheduled_time)`) → noto'g'ri soat tavsiyasi | `database.py:4203-4211` |
| P1-L | `queue_slots` `system_settings` da JSON sifatida saqlanadi (global jadval, indekssiz) | `database.py:3930-3955` |
| P1-M | RSS/URL oqimlari uchun **SSRF/URL validatsiyasi** ko'rib chiqilmagan | `utils/channel_reader.py:306-330` (`_fetch_html` — URL qabul qiladi) |
| P1-N | Telegram API va AI uchun **jonli probe** yo'q → Autopilot nosozligi aniqlanmaydi | `services/health_service.py:305-388` |

### 🟡 P2 — Keyingi bosqichlar

| ID | Xavf | Joy |
|---|---|---|
| P2-O | `MAX_AI_CONCURRENCY`/`MAX_AI_QUEUE`/`ENABLE_POLLINATIONS_FALLBACK` hujjatlashtirilmagan (25 ta env) | `.env.example` |
| P2-P | Ikki `.env.example` sinxron emas (5 ta STT o'zgaruvchisi Render nusxasida yo'q) | `.env.example` vs `telegram_bot/.env.example` |
| P2-Q | `README.md` bo'sh (21 bayt) → yangi modullar uchun hujjat joyi yo'q | `README.md` |
| P2-R | `_check_ai_providers` `provider.tier`/`key_attr` ga tayanadi (`build_default_providers`) — `services/ai/providers.py` klasslarida bunday atributlar **yo'q** (`tier` faqat `services/ai_service.py` da) | `health_service.py:322-369` — kelajakda chalkashlik |
| P2-S | HTTP `/health` autentifikatsiyasiz (DB holati oshkor bo'ladi) | `utils/web_server.py:15-45` |
| P2-T | `Mock` ishlatilgani statistikada `Mock` deb ko'rinadi, `+mock_safe` / `MockFallback` — metrika buziladi | `orchestrator.py:197-204` |

---

## 8. PHASE 1 UCHUN TAVSIYA ETILGAN KETMA-KETLIK (kod hozircha tegilmagan)

> Bu bo'lim **reja** — hech qanday kod o'zgarishi kiritilmagan. Tartib printsipi: **avval AI qatlami
> ishonchli bo'lsin, keyin yangi funksiyalar**.

| Qadam | Ish | Asos (audit) | Testlar |
|---|---|---|---|
| **1** | **AI Mock siyosati**: `AI_ALLOW_MOCK` env (default 0); zanjir tugaganda `ai_unavailable` qaytarish; `provider_used` ni DB/metrikaga yozish | P0-A, P0-D | `tests/ai_orchestrator_test.py:145-159` va `tests/ai_advanced_features_test.py` (5-band) **yangilanishi kerak** — Mock faqat flag bilan |
| **2** | **Validator tuzatish**: `orchestrator.py:193` bypass'ni olib tashlash; retry ham `is_valid` bo'lmasa `error_code` bilan qaytarish | P0-B | `tests/ai_orchestrator_test.py` retry testlari |
| **3** | **Prompt leakage**: Mock promptni postga qo'ymasligi; ichki addon matnini ajratish | P0-C | yangi test: "postda 'MUHIM:'/'IMPORTANT:' ichki instruksiya bo'lmasligi" |
| **4** | **Health kengaytmasi**: Telegram `getMe` probe, AI jonli probe (arzon `max_tokens=1`), `mock_used_24h`, navbat holati, `/health/ready?detail=1` (token bilan) | P2-R, P1-N, 3.3 | `telegram_bot/tests/health_monitoring_test.py` |
| **5** | **Team access poydevori**: `channel_members` jadvali + `db.user_can_edit_channel()` + barcha handler'larni shunga o'tkazish + kesh invalidatsiyasi | P1-E, P1-F | yangi RBAC test fayli (`tests/rbac_security_test.py` uslubida) |
| **6** | **Channel DNA** (1-versiya): `channel_dna` JSONB + AI tahlil (`channel_voice_analysis_callback` kengaytmasi) + generatsiyaga **majburiy** uzatish (magic_post/magic/DNA manbasi) | 4.3 | `tests/channel_reader_test.py` + yangi DNA testi |
| **7** | **Smart Best Time**: `channel_posts_history` dan soat→o'rtacha views agregatsiyasi (TZ bilan), slot tavsiyasi, `queue_slots` ni kanal darajasida normallashtirish | P1-K, P1-L, 5.6 | yangi test: TZ chegarasi + bo'sh ma'lumotda default slotlar |
| **8** | **7-Day Autopilot**: `scheduled_posts.origin` + `channel_autopilot` + refill job (mavjud `check_and_send_posts` yonida, `misfire_grace_time` bilan) + quiet hours (reschedule yondashuvi) + FREE limit siyosati | P1-G, P1-H, 4.5 | `tests/scheduler_service_test.py` uslubida + navbat limiti testi |
| **9** | **URL→Post**: SSRF himoyasi (faqat `http/https`, private IP blok, redirect chegarasi, timeout), kontent ajratish sifati, manba ko'rsatish | P1-M | `tests/image_post_fallback_test.py` uslubida |
| **10** | **RSS** (yangi modul): `feed_sources` + `feed_items` (guid dedupe), ingest job, AI rewrite pipeline (DNA bilan), moderatsiya | 6-jadval (RSS: 5%) | yangi test: dedupe + buzilgan XML + rate limit |
| **11** | **Content Recycle**: "top postlar" tanlash (views + vaqt), `content_hash` orqali takrorlanishni bloklash, qayta ishlanganini belgilash | 6-jadval (45%) | yangi test: bir post ikki marta qayta ishlanmasligi |
| **12** | **Env/CI gigiena**: ikki `.env.example` sinxronizatsiyasi, 25 ta yetishmagan o'zgaruvchi, eskirgan modellar, i18n (uz/ru/en) va callback-prefix/FSM-holat band qilish qoidalari | 2-bo'lim | `tests/i18n_full_parity_test.py`, `tests/final_acceptance_suite_test.py` |

### 8.1. Har bir yangi funksiya uchun **majburiy** ro'yxat (repo konventsiyalari)

1. **i18n**: barcha matnlar `uz/ru/en` da (`locales/translations.py` yoki `translations/` paketi) —
   CI `i18n_full_parity_test.py` / `i18n_ai_parity_test.py` bilan tekshiradi.
2. **Kvota**: `database.AI_OPERATION_TYPES` (`database.py:4806-4809`) ga yangi operatsiya turi yoki mavjudini
   ishlatish; `INTENT_QUOTA_OPERATIONS` (`services/ai/orchestrator.py:49-58`) bilan moslik.
3. **Sanitizatsiya**: foydalanuvchiga chiqadigan har qanday matn `utils.telegram_sanitizer.sanitize_html()` +
   4096 chunk (`smm_common.render`).
4. **Handler ro'yxati**: `handlers/__init__.py:732` (`register_all_handlers`, registratsiyalar ~1560+) — noyob callback prefiksi
   (`mp_`, `vp_`, `ps_`, `ch_`, `qslots:` band!). Stale-callback handler ham qo'shilishi kerak.
5. **FSM holatlari**: noyob raqamlar (masalan magic/voice 430-442, manual 450-454, post_score/calendar 460+
   — yangi funksiyalar uchun bo'sh diapazon tanlash).
6. **DB**: `schema.sql` + `database.py:1564-1646` `migrations` ro'yxatiga **idempotent** qo'shish;
   `ADD COLUMN IF NOT EXISTS` yoki `CREATE TABLE IF NOT EXISTS`.
7. **Test**: `telegram_bot/tests/*` (ichki runner) va/yoki `tests/*` (yuqori daraja) — CI ikkalasini ishga tushiradi.
8. **Sent-journal / delivery**: yangi post turlari `post_type` maydoniga yoziladi; `scheduler._execute_send`
   dagi `pt == "<type>"` switch'iga (`scheduler.py:1161-1209`) yangi tur qo'shilsa — `post_deliveries`
   idempotentligi va `sent_post_messages` (auto-delete) bilan mosligi tekshirilishi shart.

---

## 9. ILOVALAR

### 9.1. Audit qamrovi (nima tekshirildi)

| Soha | Fayllar |
|---|---|
| AI qatlami | `services/ai/*` (12 modul, 5 798 satr), `services/ai_service.py` (970), `services/ai_quota.py`, `utils/ai_agent.py`, `utils/vision_analyzer.py`, `utils/audio_transcriber.py` |
| DB | `schema.sql` (596), `database.py` (6 082), migratsiya mexanizmi, indekslar, constraintlar |
| Scheduler | `scheduler.py` (1 446), `services/scheduler_service.py`, `services/cleanup_service.py`, `main.py` (528) |
| Health | `services/health_service.py` (677), `handlers/health.py`, `utils/web_server.py`, `Dockerfile`, `docker-compose.yml` |
| Konfiguratsiya | `.env.example` (ikkalasi), `config.py`, `requirements.txt`, `.github/workflows/ci.yml` |
| Handler/UI | `handlers/*` (34 fayl), `keyboards/*`, `translations/*`, `locales/*` |
| Testlar | `telegram_bot/tests/*` (36), `tests/*` (27), `run_tests.sh` (ikkalasi) |

### 9.2. O'tkazilgan runtime eksperimentlar (kod o'zgarmagan)

1. `/tmp/venv` yaratildi va `telegram_bot/requirements.txt` o'rnatildi (repo ichida hech narsa o'zgarmadi).
2. `ProviderChain.execute()` — AI kalitlar yo'q holatda → `provider_used = "Mock"`, natija validator'dan
   `is_valid=True` o'tdi.
3. `AIOrchestrator.orchestrate(db_module=False)` → `success=True`, `provider_used="Mock"`.
4. Retry bypass: `LANGUAGE_MISMATCH`, `INVALID_CHARACTERS`, bo'shliqli javob — uchtasi ham qabul qilindi;
   bo'shliqli holatda Mock matni ichki retry-instruksiyasi bilan chiqdi.
5. `git status --porcelain` → **bo'sh** (kod o'zgartirilmagan).

### 9.3. Tasdiqlangan "yaxshi" tomonlar (regressiya qilmang!)

* `post_deliveries` + `FOR UPDATE SKIP LOCKED` — dublikat post yo'q (P0 topilmalari asosida).
* Restart recovery, UNKNOWN_DELIVERY siyosati (blind retry yo'q), FloodWait'da scheduler bloklanmaydi.
* Atomik AI kvota + `credits_ledger` auditi + fail-closed refund.
* `services/ai/concurrency.py` — navbat, bekor qilish, idempotent refund.
* `tone_of_voice` + `channel_posts_history` + `channel_voice_analysis_callback` — DNA uchun **haqiqiy poydevor**.
* `db.schedule_week_posts()` — 7-kunlik rejani **bitta tranzaksiyada** navbatga qo'yadi (Autopilot uchun tayyor primitiv).
* Slotlar + `find_next_queue_slot` — Smart Best Time uchun tayyor mexanizm.
* 3 tillik i18n pariteti va CI lint gate (`ruff E9,F63,F7,F82` + `flake8`) — yangi kod shu darajani saqlashi kerak.

---

## 10. YAKUNIY XULOSA

1. **Kod bazasi yaxshi qurilgan** — yangi funksiyalar uchun poydevor (navbat, idempotentlik, slotlar,
   kanal tarixi, i18n, kvota) mavjud. Bu — katta ortiqcha.
2. **Eng katta xavf — AI qatlamida:** `services/ai/*` zanjirida Mock production'da **o'chirilmagan** va
   `orchestrator.py:193` validator'ni chetlab o'tadi. Bu ikkisi **runtime'da isbotlandi**.
3. **Yaxshi xabar:** `services/ai/*` bugun **hech bir handler tomonidan ishlatilmaydi** — ya'ni xavf hali
   foydalanuvchiga yetib bormagan va uni **arzon narxda** yopish mumkin (Phase 1, 1-3-qadamlar).
4. **Team access** — eng katta strukturaviy ish: `channel_members` jadvali + egalik tekshiruvlarini
   markazlashtirish. Autopilot va DNA'dan **oldin** bajarilishi tavsiya etiladi.
5. **RSS** — noldan yoziladi (5%), **URL→Post** va **Recycle** esa mavjud komponentlarga tayanadi.
6. **Env gigienasi** — arzon va tez: 2 dublikat, 1 eskirgan model, 25 hujjatlashtirilmagan o'zgaruvchi,
   2 sinxron bo'lmagan `.env.example`.

> **Phase 0 natijasi:** kod o'zgartirilmadi. Keyingi qadam — **9.3 va 8-bo'limdagi ketma-ketlik bo'yicha
> 1-4-qadamlarni bajarish** (AI xavfsizligi + health), so'ngra 5-qadam (Team access), keyin yangi funksiyalar.
