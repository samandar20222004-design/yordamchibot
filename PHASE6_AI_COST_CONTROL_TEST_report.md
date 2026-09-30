# PHASE 6 — TEST HISOBOTI (AI Gateway + Cost Control)

**Sana:** 2026-09-30 · **Branch:** `arena/01a0f1d6-yordamchibot` ·
**Ishga tushirish:** `bash tests/run_tests.sh` (repo ildizidan)

> Holat: **YAKUNIY RUN — 100% YASHIL (SUITE_EXIT=0)**.
> O'lchov: 2026-09-30 10:44–10:47 UTC, `python3` 3.11.2, real PostgreSQL
> (pgserver) bilan.

---

## 1. Yangi PHASE 6 test to'plamlari

### 1.1 `telegram_bot/tests/ai_gateway_cost_control_test.py` — 204 tekshiruv

| TEST | Tekshiriladigan talab | Natija |
|---|---|---|
| TEST 1 | Kanonik interfeys: `ai_gateway.generate(task=..., prompt=..., user_id=..., channel_id=..., lane="fast"/"smart"/"premium")`; eski delegatlar (`gateway.generate`, `services.ai_engine.generate`); facade ↔ servis bir xilligi; lane aliaslari (fast/smart/premium/tez/sifat/chuqur/rasm) | ✅ 0 xato |
| TEST 2 | Router: `social_post→FAST`, `channel_dna→REASONING`, `post_score→QUALITY`, `repurpose→QUALITY`, noma'lum task → xavfsiz QUALITY | ✅ 0 xato |
| TEST 3 | Telemetriya: `model`, `provider`, `input_tokens`, `output_tokens`, `latency_ms`, `estimated_cost`, `priced`, `status`; xato ham yoziladi; **noma'lum model → `priced=False`, `cost=0`** (to'qima raqam yo'q); kesh hit = 0 xarajat; kunlik/oylik/**all** hisobot; user va kanal kesimi; `by_provider/by_model/by_task/by_lane/by_day`; vaqt oynasi deterministik | ✅ 0 xato |
| TEST 4 | Application Service: atomik kvota bron (AYNAN 1 marta), rad etilsa AI chaqirilmaydi, xatoda TO'LIQ refund, DB telemetriya yozuvi (maydonlar to'plami), `usage_report` (DB+memory), `quota_status` | ✅ 0 xato |
| TEST 5 | Mock siyosati: production'da `off` + zanjirdan CHIQARILADI (fail-closed), `test`/`development` alohida rejimlar, `AI_ALLOW_MOCK=1` — `forced`, `ENVIRONMENT` yo'q → production fail-closed | ✅ 0 xato |
| TEST 6 | Retry/fallback/breaker: 429 → AYNAN 2 urinish (1+1) → keyingi provayder; dasturiy xato → 1 urinish; sifat rad etilsa 1 retry (retry ko'rsatmasi biriktiriladi); breaker ochilgach provayder sinalmaydi; `provider_chain`/`attempts` qayd etiladi; FAST — kutishsiz, QUALITY — backoff; backoff byudjetga mos | ✅ 0 xato |
| TEST 7 | Prompt guard + qat'iy validator: kirishdan ko'rsatmalar tozalanadi, mazmun saqlanadi; `[SYSTEM]` sizib chiqsa RAD; **"uzunlik ≥ 20" bypass'i statik (6 fayl) va dinamik (yupqa/begona tilli 20+ belgili matnlar rad etiladi) tekshirilgan**; sxema buzilsa `INVALID_SCHEMA`; bo'sh javob `ok=True` bo'lmaydi | ✅ 0 xato |
| TEST 8 | Handler izolyatsiyasi (provayder qatlamiga to'g'ridan-to'g'ri bog'lanish yo'q), legacy adapter (`services.ai_service.run_ai_chain`) o'zgarmagan va telemetriyaga yoziladi, `gateway_status()` (mock/usage/lane), `ai_engine` eksportlari | ✅ 0 xato |

**Natija:** `JAMI: o'tdi=204, xato=0 — PHASE 6 — AI GATEWAY & COST CONTROL 100% YASHIL ✔`

### 1.2 `telegram_bot/tests/ai_cost_tracking_db_test.py` — 49 tekshiruv (REAL PostgreSQL / pgserver)

| Guruh | Tekshiriladigan talab | Natija |
|---|---|---|
| 1. Statik sxema | `AI_USAGE_TABLES/INDEXES`, `schema.sql` (jadval + 2 indeks, **literal hisob 31 saqlangan**), 20 ustun, facade funksiyalari (`save_ai_usage_event`, `get_ai_usage_report`, `purge_ai_usage_events`) | ✅ |
| 2. Yozuv modeli | `AIUsageEvent.to_row()` 18 ustun, status CHECK qiymati, `priced`/`estimate_cost` semantikasi | ✅ |
| 3. Real baza | Jadval/ustunlar/indekslar real PostgreSQL'da; `save_ai_usage_event` ID qaytaradi; yaroqsiz status majburan `failed`; kunlik hisobot (requests/successes/failures/tokenlar/xarajat/priced); **kanal kesimi va izolyatsiya**; `daily`/`monthly` (`by_day`)/`all`; noto'g'ri davr → xavfsiz `daily`; **retention** (`purge_ai_usage_events(days=7)` eski yozuvni o'chiradi, yangilar qoladi); `run_ai_task` real adapterga yozadi va `usage_id` qaytaradi | ✅ |

**Natija:** `JAMI: o'tdi=49, xato=0 — PHASE 6 — AI COST TRACKING 100% YASHIL ✔`

Ikkala test ham runnerlarga ulangan:
`telegram_bot/tests/run_tests.sh` (PHASE 6 bo'limi, ikkalasi ham) — root runner ularni
«4) TO'LIQ REGRESSIYA (telegram_bot/tests)» bosqichida ishga tushiradi.

---

## 2. Maqsadli regressiya (o'zgartirilgan modullar)

| Test | Natija |
|---|---|
| `tests/ai_engine_v2_test.py` | o'tdi=146, xato=0 |
| `tests/production_safety_and_validator_test.py` | o'tdi=58, xato=0 |
| `tests/ai_prompt_quality_test.py` | o'tdi=155, xato=0 |
| `tests/repository_layering_test.py` (yangi repo funksiyalari) | o'tdi=99, xato=0 |
| `telegram_bot/tests/schema_test.py` (real PostgreSQL) | o'tdi=181, xato=0 |
| `telegram_bot/tests/db_integrity_test.py` | o'tdi=208, xato=0 |
| `tests/env_docs_parity_test.py` (yangi env yo'q — paritet saqlangan) | o'tdi=45, xato=0 |
| `tests/content_calendar_flow_test.py` | o'tdi=25, xato=0 |
| `tests/refactor_step2_test.py` (kontent-reja mock nuqtasi) | o'tdi=170, xato=0 |

---

## 3. To'liq regressiya

| Ko'rsatkich | Qiymat |
|---|---|
| Buyruq | `bash tests/run_tests.sh` (repo ildizidan) |
| SUITE_EXIT | **0** |
| `[FAIL]` qatorlari | **0** (butun log bo'ylab) |
| Ichki regressiya yakuni | `BARCHA TESTLAR MUVOFFAQIYATLI ✔` |
| Root runner yakuni | `BARCHA TESTLAR 100% YASHIL ✔` |
| Muvaffaqiyatli tekshiruvlar | **14 408 ta `[OK]`** (shundan 253 tasi — yangi PHASE 6 testlari: 204 + 49) |
| Kuzatilgan xatolar | 0 |
| Log | `/tmp/p6final.log` (18 718 qator) |

Yakuniy satrlar (log'dan aynan):

```
 JAMI: o'tdi=204, xato=0
 PHASE 6 — AI GATEWAY & COST CONTROL 100% YASHIL ✔
===== 💰 PHASE 6 — AI XARAJAT JURNALI + HISOBOT (REAL POSTGRESQL) =====
 JAMI: o'tdi=49, xato=0
 PHASE 6 — AI COST TRACKING 100% YASHIL ✔
BARCHA TESTLAR MUVOFFAQIYATLI ✔
==============================================================
BARCHA TESTLAR 100% YASHIL ✔
SUITE_EXIT=0
```

### 3.0 Main (PHASE 5) ustiga rebase'dan keyingi tasdiqlash ✅

`main` shoxobchasi PHASE 5 (markaziy Telegram delivery engine) commit'i
(`958a618`) bilan oldinga surilgach, PHASE 6 kommitlari **to'g'ridan-to'g'ri
`origin/main` ustiga rebase qilindi** — tarix chiziqli (merge commit'siz),
shuning uchun GitHub'da «Rebase and merge» ham ishlaydi.

Konflikt faqat `telegram_bot/tests/run_tests.sh` da edi — **ikkala bo'lim ham
saqlandi** (PHASE 5 delivery-engine testi + PHASE 6 ning ikkala testi).
Rebase'dan keyingi kod daraxti avval tekshirilgan daraxt bilan **aynan bir
xil** (`git diff <eski> <yangi> --stat` bo'sh), ya'ni quyidagi natijalar
o'sha kodga tegishli.

| Tekshiruv | Natija |
|---|---|
| Lokal to'liq regressiya (`bash tests/run_tests.sh`, main ustiga qo'shilgandan keyin) | **14 457 `[OK]`, 0 `[FAIL]`, `SUITE_EXIT=0`** — `BARCHA TESTLAR 100% YASHIL ✔` |
| Lint gate (CI bilan bir xil): `ruff --select=E9,F63,F7,F82` | `All checks passed!` |
| Lint gate: `flake8 --select=E9,F63,F7,F82` | `0` |
| GitHub Actions «PostAssist V2 CI» (`test`) | **✓ pass** |
| Tarix | `958a618` (main) → `e531774` (PHASE 6) → report commit — chiziqli |
| Log | `/tmp/p6merge.log` |

### 3.1 Yo'l-yo'lakay topilgan va tuzatilgan muammolar

1. **`ai_usage_events` yozuvi commit qilinmasdi** — `db_cursor()` o'qish rejimida
   ishlaydi; yozuv funksiyalari `db_cursor(commit=True)` ga o'tkazildi
   (real bazada INSERT/RETURNING natijasi saqlanadi).
2. **Hisobot SQL'i** `WHERE ... TRUE ...` shaklida sintaksis xatosi berardi —
   shartlar to'g'ri birlashtirildi (`WHERE TRUE AND ...` emas, balki
   `WHERE <shartlar> <oyna>`).
3. **`period="all"` cheksiz oyna** (`float("inf")`) ISO vaqtni hisoblashda
   `OverflowError` berardi — oyna `1970 → hozir` bilan cheklandi.
4. **Handler mock nuqtasi** — kontent-reja endi `user_id` kontekstini
   uzatadi; testlar eski imzoli fake bilan ishlashi uchun kontekst
   `pick_supported_kwargs` orqali FAQAT funksiya qabul qilsa uzatiladi
   (backward compatibility).
5. **Router'dagi takroriy `image_post` kaliti** olib tashlandi
   (xatti-harakat o'zgarmadi: `image_post` → VISION).

---

## 4. Talablar → dalillar xaritasi

| PHASE 6 talabi | Dalil |
|---|---|
| Yagona kanonik interfeys | `services/ai_gateway.py` facade; `ai_gateway.generate(task, prompt, user_id, channel_id, lane)`; TEST 1/2/8 |
| Qatlamlar: Handler → App Service → Gateway → Router → Provider | `app_service.py` (bron/refund/DB), `gateway.py` (router/health/retry/providers/validator/cache), TEST 4/6 |
| Har so'rov uchun model/provider/tokenlar/latency/xarajat/status | `telemetry.AIUsageEvent` + `ai_usage_events`; TEST 3 (kod) + `ai_cost_tracking_db_test.py` (real DB) |
| Kunlik/oylik hisobot user va kanal kesimida | `get_ai_usage_report(..., period=daily|monthly|all)`; TEST 3d/4d; DB test 3b–3d |
| Breaker/timeout/fallback/retry mustahkamlash | `retry.py` (yagona siyosat), `health.py`, TEST 6 |
| Mock production'da default O'CHIQ, test/dev alohida | `mock_mode()` (off/test/development/forced), TEST 5 |
| Prompt-injection himoya + qat'iy validator, bypass yo'q | `prompt_guard.py`, `safety.py`, `validator.py`, TEST 7 (statik + dinamik) |
| O'zgarishlar faqat `telegram_bot/` ichida | `PHASE6_CHANGES.diff`: 14 fayl, +3977/−198 — barchasi `telegram_bot/` ostida |
| Mavjud funksiyalar/importlar buzilmagan | TEST 1c/8b + to'liq regressiya |
| 0 [FAIL], SUITE_EXIT=0 | Yuqoridagi 3-bo'lim: 0 `[FAIL]`, SUITE_EXIT=0, 14 408 `[OK]` |
