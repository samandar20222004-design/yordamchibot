# 🚦 AI ENGINE V2 — YAGONA AI SHLYUZ VA MODEL ROUTER (2-SPRINT: FAZA 1, 2, 3, 21)

**Sana:** 2026-09-18 · **Branch:** `arena/01a0b3f2-yordamchibot`
**Manba:** `DEEP_AUDIT_REPORT.md` — "AI chaqiruvlari ikkiga bo'linib ketgan:
eski modullar `utils/ai_agent.py` ga, yangilari esa `services/ai/*` ga
murojaat qilmoqda. Yagona marshrutlash (routing) va tezkor kesh yo'q."

**Qat'iy qoida bajarildi:** hech narsa noldan qayta yozilmagan — barcha real
HTTP provayderlari, kvota, validator, navbat va timeout mexanizmlari
o'z joyida qoldi; yangi shlyuz ularni YIG'IB, yagona kanonik kanalga
birlashtirdi. To'liq regressiya **BASH EXIT CODE = 0** (100% yashil).

---

## 1. YAGONA KANONIK AI SHLYUZ — `telegram_bot/services/ai_engine/`

Yangi paket (5 modul + `__init__`):

| Modul | Vazifa |
|---|---|
| `gateway.py` | Yagona `generate` / `analyze` / `vision_analyze` interfeysi + `legacy_chain` adapteri + `gateway_status()` diagnostika |
| `router.py` | Model tanlash: **FAST / QUALITY / REASONING / VISION** lane'lari, vazifa→lane xaritasi, prompt-based auto-detect |
| `providers.py` | Provayder registrı (Gemini, Groq, OpenRouter + chuqur zanjir) — real HTTP `services/ai_service.py` adapterlarida, takrorlanmagan |
| `health.py` | **Circuit Breaker**: 429/timeout/5xx/tarmoq klassifikatsiyasi, ketma-ket xatolar soni, sog'lom provayderga avto-fallback |
| `cache.py` | **Deterministik kesh**: sha256 kalit, TTL (default 900s) + LRU (512) |

### Arxitektura (qatlamlar)

```
handler / xizmat
    └─ gateway.generate / analyze / vision_analyze   ← YAGONA KIRISH
         ├─ cache.get  (FAST lane — deterministik kalit)
         ├─ router.resolve_lane → FAST/QUALITY/REASONING/VISION
         ├─ health.healthy_order  (circuit breaker — 429/timeout/5xx)
         ├─ providers.execute_provider (services/ai_service adapterlari)
         └─ cache.set  (muvaffaqiyatda)

Eski chaqiruvlar (backward compatibility):
    utils/ai_agent._run_ai_chain → gateway.legacy_chain →
    services.ai_service.run_ai_chain   (8-provayderli legacy zanjir O'ZGARMAGAN)
```

### Handler izolyatsiyasi (audit qoidasi: "hech bir handler provayderga
to'g'ridan-to'g'ri bog'lanmasin!")

| Handler | Oldin | Endi |
|---|---|---|
| `handlers/post_score.py` | `from services.ai_service import improve_post_to_95, score_post` | `from services.ai_engine.gateway import ...` (kechikkan bog'lanishli delegat) |
| `handlers/image_post.py` | `from services.ai_service import generate_image_post` | `from services.ai_engine.gateway import ...` |
| `handlers/manual_post.py` | `from services.ai_service import run_ai_chain` (funksiya ichida) | `gateway.legacy_chain(...)` |
| `handlers/content_calendar_flow.py` | `from services.ai_service import run_ai_chain` (funksiya ichida) | `gateway.legacy_chain(...)` |
| barcha qolgan handler'lar | `utils/ai_agent.*` | o'zgarmagan — endi ular avtomatik shlyuz kanaliga tushadi (`_run_ai_chain` adapteri) |

Delegatlar **late binding** bilan yozilgan: `services.ai_service.X`
monkeypatch qilinsa, delegat ham yangi qiymatni ko'radi — barcha eski
test patch nuqtalari ishlashda davom etadi.

## 2. MODEL ROUTER VA FAST PATH (Faza 2)

| Lane | Vazifalar | Provayder tartibi | Timeout | Kesh |
|---|---|---|---|---|
| **FAST** | qayta yozish, oddiy post, tuzatish, qisqartirish, format, FAQ | **Groq** → Gemini → OpenRouter → chuqur zanjir | **12s** (`AI_FAST_PATH_TIMEOUT`, 10–15s oyna) | ✅ default |
| **QUALITY** | audit, tahlil, post_score, variantlar | **Gemini** → Groq → chuqur zanjir | 25s | ❌ (so'ralsa) |
| **REASONING** | kanal tahlili, haftalik reja, kontent-reja, DNA, best-time | **Gemini** → OpenRouter → Groq → chuqur zanjir | 30s | ❌ (so'ralsa) |
| **VISION** | rasm tahlili, image→post | **Gemini (Vision)** → chuqur zanjir | 25s | ❌ |

* **Fast Path**: oddiy so'rovlar og'ir modellar navbatida qotib qolmaydi —
  qat'iy umumiy timeout (`asyncio.wait_for`), kesh tekshiruvi BIRINCHI
  qadamda (hit → provayderga chiqmasdan javob), muvaffaqiyat keshga yoziladi.
* Auto-detect: aniq `task`/`lane` > prompt signallari > SMM Intent Router
  (`services.ai.router` — yagona manba, sinxron: IMPROVE/CREATE → FAST,
  AUDIT → QUALITY, IDEAS → REASONING) > xavfsiz standart QUALITY.
* `resolve_handles()` kalitlarni CHAQIRUV paytida tekshiradi — kaliti yo'q
  provayder lane'dan butunlay chiqadi.

## 3. CIRCUIT BREAKER (health.py)

* Klassifikatsiya: `429/rate limit/quota` → `rate_limit`, `timeout` →
  `timeout`, `5xx` → `server_error`, `connection/ssl/dns` → `network`.
* Ketma-ket `AI_BREAKER_THRESHOLD` (default 3) xato → provayder
  `AI_BREAKER_COOLDOWN` (default 600s) ga **ochiladi** (legacy
  `BREAKER_THRESHOLD/COOLDOWN` bilan bir xil siyosat).
* `healthy_order()` — ochiq breaker'li provayder ro'yxat OXIRIGA suriladi:
  so'rov avtomatik SOG'LOM provayderdan boshlanadi (avto-fallback).
* Muvaffaqiyat breaker'ni tozalaydi (half-open yopiladi).
* **Yagona sog'liq holati**: monitor holati legacy
  `utils.ai_agent._BREAKERS` lug'atiga MIRROR qilinadi — legacy zanjir
  (`AIFallbackService`) va yangi gateway BITTA breaker siyosatida yashaydi.
* Snapshot: `gateway_status()["health"]` (admin diagnostikasi uchun tayyor).

## 4. DEAD-END TUZOQLAR (Faza 21)

| Joy | Oldin | Endi |
|---|---|---|
| `handlers/ai_post.py::build_clarification_keyboard` | 5 tugma, chiqish YO'Q (`aip_back` callback'i esa begona — unga bog'langan tugma umuman yo'q edi) | `[❌ Bekor qilish]` (`aip_cancel`) alohida oxirgi qatorda — layout `2+2+1+1`; callback wizard kalitlarini tozalaydi, FSM yopadi, `ConversationHandler.END` |
| `handlers/magic_post.py::_magic_style_keyboard` | 5 uslub tugmasi, chiqish YO'Q | `[❌ Bekor qilish]` (`mp_cancel`) oxirgi qatorda — layout `3+2+1`; `magic_cancel_callback` sessiya kalitlarini tozalaydi (`magic_raw_text` va h.k.), `clear_fsm_data`, END — kredit/limit TIYILMAYDI (hech narsa bron qilinmagan) |

* Routerda ro'yxatdan o'tgan: `MAGIC_STYLE_SELECT` va `AI_POST_CLARIFY`
  holatlarida `^mp_cancel$` / `^aip_cancel$` (`handlers/__init__.py`).
* i18n: `mp_btn_cancel`/`mp_cancel_done` (uz/ru/en) +
  `_AIP_TEXTS` `cancel_button`/`cancel_done` (uz/ru/en) — paritet testlari
  yashil (`magic_post_parity_report()["in_sync"] is True`).
* Konventsiyalar saqlandi: `await query.answer()` boshida, ≤64 bayt
  callback, stale qo'riqchi (`^mp_`, `^aip_`) o'zgarmagan.

## 5. TEST VA NATIJA

* **Yangi suite:** `tests/ai_engine_v2_test.py` — 146 tekshiruv, 7 bo'lim:
  router (lane xaritalari, ustuvorlik, provider order), deterministik kesh
  (kalit/TTL/LRU/stats), circuit breaker (klassifikatsiya, ochilish,
  avto-fallback, legacy mirror), gateway (fail-soft, 429→zaxira, kesh hit
  provaydersiz, force_refresh, Fast Path qat'iy timeout ~0.5s, analyze,
  vision delegat), legacy adapter (eski monkeypatch nuqtalari buzilmaydi),
  handler izolyatsiyasi (statik scan: `services.ai_service` /
  `services.ai.providers` handler'larda YO'Q), dead-end tuzoqlar.
* Runner'ga ro'yxatdan o'tdi: `tests/run_tests.sh` → **3J** bo'limi;
  `telegram_bot/tests/syntax_test.py` ga 5 modul import tekshiruvi qo'shildi.
* Mavjud 3 test yangi UI spetsifikatsiyasiga moslandi (faqat klaviatura
  sonlari: 5→6 tugma, layout `+1` qator; oqim mantiqi o'zgarmagan):
  `ai_clarification_and_intent_test.py`, `magic_post_flow_test.py`,
  `post_score_flow_test.py`.

### Yakuniy buyruq va natija

```
$ PYTHON=/tmp/venv/bin/python bash tests/run_tests.sh
$ echo "BASH EXIT CODE: $?"
BASH EXIT CODE: 0        ← BARCHA TESTLAR 100% YASHIL ✔ (0 ta [FAIL])
```

## 6. YANGI ENV O'ZGARUVCHILARI (ikkala `.env.example` da hujjatlangan)

| O'zgaruvchi | Default | Ma'no |
|---|---|---|
| `AI_FAST_PATH_TIMEOUT` | `12` | Fast Path qat'iy umumiy muddati (soniya, 10–15s oyna) |
| `AI_CACHE_TTL` | `900` | Kesh TTL (soniya; `0` = kesh o'chiriladi) |
| `AI_CACHE_MAX_ENTRIES` | `512` | Kesh LRU sig'imi |
| `AI_BREAKER_THRESHOLD` | `3` | Ketma-ket xatolar chegarrasi (breaker ochilishi) |
| `AI_BREAKER_COOLDOWN` | `600` | Breaker cooldown (soniya) |

`env_docs_parity_test.py` yashil: dublikat yo'q, ikkala nusxa paritetda,
orphan yo'q.

## 7. NIMA O'ZGARMADI (ataylab — "hech narsa noldan qayta yozilmaydi")

* `services/ai_service.py` — 8 provayderli zanjir, qat'iy per-provayder
  timeout, 429 retry, model discovery: BITTA katorga tegilmadi.
* `services/ai/*` (SMM orkestrator, kvota, validator, navbat, promptlar) —
  o'z ishida; u kvota/validator bilan ishlaydigan YUQORI qatlam bo'lib qoladi.
* `utils/ai_agent.py` — faqat `_run_ai_chain` ichi adapterga yo'naltirildi
  (9 qator farq); barcha public funksiyalar va test hook'lari saqlangan.
* `utils/vision_analyzer.py` — Vision model zanjiri o'zgarmagan; gateway
  uni o'raydi (`vision_analyze`).
* P0-A Mock siyosati, kvota refund, HTML sanitizer — buzilmagan
  (production_safety testlari yashil).
