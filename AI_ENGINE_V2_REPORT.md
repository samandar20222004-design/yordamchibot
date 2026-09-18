# 🚦 AI ENGINE V2 REPORT — YAGONA KANONIK AI SHLYUZ

> **Holat:** ✅ PASS — `tests/ai_engine_v2_test.py` (129 PASS) + FAZA 23/25
> hardening kengaytmalari bilan birga **BASH EXIT CODE: 0**.
> **Modullar:** `telegram_bot/services/ai_engine/` — `gateway.py`, `router.py`,
> `cache.py`, `providers.py`, `schemas.py`, `safety.py`, `validator.py`,
> `prompts.py`, `health.py` · `telegram_bot/services/ai/` — `orchestrator.py`,
> `concurrency.py`, `prompt_guard.py`, `smm_common.py` …

Bu hisobot DEEP AUDIT (Faza 1/2/3/21) va 8-sprint (Faza 23/25) yakunlari
asosida AI dvigatelining yakuniy arxitekturasi va kafolatlarini jamlaydi.

---

## 1. Gateway — yagona kirish nuqtasi (`services/ai_engine/gateway.py`)

- `generate` / `analyze` / `vision` kanonik API'lari; **legacy adapter**
  (`utils/ai_agent.py` eski chaqiruvlari shlyuz orqali o'tadi — backward
  compatibility: `provider`/`provider_chain` shakli va eski monkeypatch
  nuqtalari buzilmaydi).
- **Fail-soft**: provayder xatosi istisno sifatida "portlamaydi" —
  muloyim, lokalizatsiyalangan xabar qaytadi; 429 → keyingi sog'lom
  provayderga o'tadi.
- `force_refresh` (keshni chetlab o'tish), **Fast Path qat'iy umumiy
  timeout** — `asyncio.wait_for` bilan (10–15 s, lane bo'yicha).
- Handler izolyatsiyasi: **hech bir handler provayder qatlamiga
  to'g'ridan-to'g'ri bog'lanmaydi** — hammasi gateway yoki legacy adapter
  orqali (test bilan qulflangan).

## 2. Model Router (`services/ai_engine/router.py`)

Vazifaga qarab lane tanlanadi; router tarmoqqa CHIQMAYDI — faqat kanonik
provayder NOMLARI tartibini qaytaradi (`services/ai_service.py`
adapterlari bilan bir xil: Gemini, Groq, OpenRouter, Mistral, Cerebras,
SambaNova, Cloudflare, Pollinations):

| Lane | Vazifa turlari | Siyosat |
|---|---|---|
| **FAST** | qayta yozish, oddiy post, tuzatish, formatlash, uslub | eng tez provayder birinchi; 10–15 s qat'iy timeout; kesh-first |
| **QUALITY** | audit, tahlil, batafsil javoblar | sifatli provayderlar ustuvor |
| **REASONING** | kanal tahlili, haftalik kontent-reja, DNA | chuqur tahlil provayderlari |
| **VISION** | rasm tahlili | Gemini Vision zanjiri |

SMM Intent Router bilan sinxron (aniqlashtirish wizard'i qarorlari bir xil
lane'ga tushadi).

## 3. Deterministik kesh (`services/ai_engine/cache.py`)

- Kalit: `sha256(lane | task | lang | tone | is_pro | system | prompt)` —
  bir xil so'rov → aynan bir xil kalit, **provayder tartibidan MUSTAQIL**
  (fallback provayder almashtirganda ham hit).
- **TTL** (standart 15 daqiqa) + **LRU** (standart 512 yozuv) — xotira
  cheklangan; hit provayderga UMUMAN chiqmaydi (Fast Path).
- Faqat FAST lane default keshlanadi; Quality/Reasoning — faqat aniq
  so'ralganda (kontekst sezgank).

## 4. Circuit Breaker va sog'liq (`gateway.py`, `health.py`)

- Xato klassifikatsiyasi: 429 / timeout / 5xx; ketma-ket xatolar
  chegarasidan oshganda provayder **vaqtincha ochiladi**, so'rov sog'lom
  provayder ro'yxati BOShINGA tushadi (avto-fallback).
- Legacy `_BREAKERS` mirror — shlyuz va eski zanjir YAGONA sog'liq
  holatini ko'radi (ikki "haqiqat" yo'q).
- Navbat qatlami: `services/ai/concurrency.py` —
  `MAX_AI_CONCURRENCY` semafori + `MAX_AI_QUEUE` bounded queue:
  navbat to'lganda **fail-closed** `AIQueueFullError` (⏳ muloyim xabar),
  kvota/kredit to'liq refund (idempotent), task/registry tozalanadi.

## 5. Sxemalar va validatsiya (`schemas.py`, `validator.py`)

- Chiqish sxemalari: javob faqat kutilgan shaklda qabul qilinadi
  (JSON sxema tekshiruvi, noto'g'ri tuzilma → qat'iy retry sikli,
  "soxta OK" yo'q).
- Sifat validatori: yupqa/javobsiz holatda qayta urinish; prompt/retry
  ko'rsatmalarining javobga SIZIB chiqishi bloklanadi —
  `production_safety_and_validator_test.py` (P0-A/B/C) yashil.
- Production rejim: `ENVIRONMENT=production` va `AI_ALLOW_MOCK=0`
  da Mock zanjirdan butunlay chiqariladi (fail-closed) — mock faqat
  dev/test'da.

## 6. Injection himoyasi (`safety.py` + `services/sources/url_extractor.py`)

Ishonchsiz (UNTRUSTED) matn — foydalanuvchi yoki tashqi manba — hech
qachon tizim ko'rsatmasiga aylanmaydi:

- `untrusted_input()` — HTML-escape + `<untrusted_input>` fence.
- URL→post oqimi: `build_untrusted_block()` —
  `<<<UNTRUSTED_SOURCE>>> … <<<END_UNTRUSTED_SOURCE>>>`; matn ichidagi
  fence belgilari olib tashlanadi (matn blokni "yopa olmaydi");
  `neutralize_untrusted_text()` — `<system>`, `<|im_start|>`, qator
  boshidagi `SYSTEM:`/`ASSISTANT:` rollari va "ignore previous
  instructions" kabi markerlar **`[⛔ ko'rsatma olib tashlandi]`** bilan
  almashtiriladi; `detect_prompt_injection()` signal ro'yxati (uz/ru/en
  markerli).
- `contains_leak()` — javob ichida tizim prompti, `API_KEY/TOKEN/SECRET`
  qiymatlari (env skaneri bilan) ko'rinsa → javob qabul qilinmaydi.
- Reklama dvigateli: NO FABRICATION — to'qilgan narx/kafolat/reyting/
  sertifikat postga tushmaydi (jumla darajasida olib tashlanadi +
  `removed_claims` qayd etiladi); sayt paywall/login devorini **chetlab
  o'tish taqiqlangan** (`paywall` kodi).

## 7. FAZA 23/25 bilan uyumlilik (8-sprint yakunlari)

- Gateway Fast Path timeout'lari ustiga **umumiy handler watchdog**
  (`UPDATE_HANDLER_TIMEOUT_SECONDS=110`) qo'yildi — hatto chaqiruvchi
  handler adashib locksiz cheksiz ketsa ham qabul zanjiri tirilmaydi
  (`main.py GuardedApplication`).
- Concurrent AI so'rovlari 40 parallel IDOR hujumi va 16 parallel sekin
  provayder simulyatsiyasida: semafor peak ≤ limit, queue fail-closed,
  barcha so'rovlar timeout izolyatsiyasida — **126 PASS** (TEST 5).

## 8. Test xulosasi

| Suite | Natija |
|---|---|
| `tests/ai_engine_v2_test.py` (1–7 band: router, kesh, breaker, gateway, adapter, izolyatsiya, dead-end) | ✅ PASS (129) |
| `tests/ai_orchestrator_test.py`, `ai_concurrency_test.py`, `ai_advanced_features_test.py`, `ai_clarification_and_intent_test.py`, `ai_prompt_quality_test.py` | ✅ PASS |
| `tests/production_safety_and_validator_test.py` (Mock siyosati, qat'iy validator) | ✅ PASS |
| `tests/production_hardening_and_concurrency_test.py` (TEST 5 — concurrent AI yuklama) | ✅ PASS |

**XULOSA: AI ENGINE V2 ishlab chiqarish darajasida — PASS ✅**
