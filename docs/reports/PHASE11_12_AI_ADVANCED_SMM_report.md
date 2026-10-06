# PHASE 11 & PHASE 12 — AI ADVANCED SMM FEATURES (33, 48, 49, 50, 51-bandlar)

**Sana:** 2026-09-16 · **Runner:** `PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh`
**Natija:** `BASH EXIT CODE: 0` · `[FAIL]` soni: **0** · `[OK]` soni: **9778** (butun suite)
yangi qamrov: `tests/ai_advanced_features_test.py` → **JAMI: o'tdi=167, xato=0**

---

## 1. Qo'shilgan xizmatlar (`telegram_bot/services/ai/`)

| Fayl | Band | Vazifa |
|---|---|---|
| `variants.py` | **48** | Multi-variant generator — bitta mavzudan **5 ta alohida burchakdagi** post |
| `repurpose.py` | **49** | Kontentni 5 ta platforma formatiga moslashtirish |
| `audit.py` | **33 + 50** | Deep Post Audit & Score — 6 mezon → 0-100 → kuchli tomonlar → Top 3 → yaxshilangan namuna |
| `planner.py` | **51** | Kontent Reja Generator — 1/7/14/30 kun (Mavzu, Format, Hook, Maqsad, CTA) |
| `smm_common.py` | — | To'rt xizmatning **yagona poydevori**: `SMMFeatureService` (kvota, AI chaqiruvi, sanitizer, chunk) |
| `smm_mock.py` | — | Deterministik javoblar banki — `MockProvider` **va** offline fallback uchun yagona manba |

### 1.1 ✨ Multi-variant (48-band)
5 uslub, har biri **o'z AI chaqiruvi va o'z formulasi** bilan (bitta javobni
qayta yozish orqali «5 variant» qilinmaydi):

1. 🔥 **Viral** — kuchli hook + munozarali savol + ulashishga chaqiriq
2. 💎 **Premium** — bosiq, lakonik, ekspert ohang (chegirma/aksiya toni taqiqlangan)
3. 💰 **Sales** — PAS (muammo → kuchaytirish → yechim) + aniq taklif + sotuv CTA
4. 📚 **Informative** — faktlar, raqamlar, 3 punktli tuzilma + ekspert xulosasi
5. 🤳 **Blogger** — samimiy shaxsiy tajriba, birinchi shaxs, ochiq savol

**Sinonimlikka qarshi qo'riq:** har bir javob `fingerprint` (normalallashtirilgan
so'z oqimi) + Jaccard o'xshashligi bilan tekshiriladi; ustma-ust tushsa — uslub
bankidagi boshqa burchakka almashtiriladi. Test: 5 variantning **10 ta juftligi**
ham mazmunan farq qiladi.

### 1.2 🔄 Repurpose (49-band)
`Telegram Post | Instagram Caption | Stories ssenariy | Reels/Shorts hook-ssenariy |
Reklama matni`. Platforma chegaralari **lokal kafolatlanadi** (model ularni
«taxminan» biladi):

* Telegram — qalin hook, ✅ punktlar, CTA, 3-5 hashtag, ≤ 4096;
* Instagram — caption ≤ **2200**, birinchi qator hook, alohida **5-10** hashtag
  bloki, «havola bio'da» konvensiyasi;
* Stories — **3-5 slayd**, har birida bitta gap ≤ **120** belgi, rol
  (muammo → dalil → yechim → CTA) va stiker ko'rsatmasi;
* Reels/Shorts — **0-3s hook** + sahna tayminglari (`3-9s`, `9-18s`, …), overlay
  yozuvi, vertikal 9:16 eslatmasi;
* Reklama — Meta maydonlari: headline ≤ **40**, primary ≤ **125**,
  description ≤ **30**, bitta CTA tugma ≤ 20.

### 1.3 🔍 Deep Audit (33 + 50-band)
6 mezon: **Hook, Clarity, Value, Structure, CTA, Engagement** (1-10 ball),
og'irliklar yig'indisi 100 → umumiy **score 0-100** + baho (A+…E) +
`█░` progress-bar + kuchli tomonlar + **Top 3 yaxshilanish** (har birida
mezon, muammo, amaliy tuzatish va kutilayotgan ball o'sishi) + **yaxshilangan
yakuniy namuna post**.

> **Arxitektura qarori:** ballar **faqat lokal hisoblagichdan** — model
> «100/100» deb yozib, baholni o'zgartira **OLMAYDI**. AI (JSON kontrakti)
> faqat matn qismlarini boyitadi: `verdict`, `strengths`, `improvements[{criterion,fix}]`,
> `improved_post`. Buzuq JSON/timeout → lokal karkas bilan hisobot baribir to'liq.

### 1.4 🗓 Content Plan (51-band)
`1 | 7 | 14 | 30` kun; har bir kunda **sana + kun nomi + publish vaqti, Format,
Mavzu, Hook g'oyasi, Maqsad, CTA va hashtaglar**. Hafta sikli (Du→ Yak) bo'yicha
format rotatsiyasi, hafta soni yumshoq kontentga suriladi. Siyosat:
FREE — 1/7 kun, **14/30 kun FAQAT PRO** (`pro_required`), boshqa davomiylik
`invalid_duration`, bo'sh yo'nalish `INVALID_INPUT`.

---

## 2. Orkestratsiya va integratsiya (avvalgi fazalar buzilmagan)

* **Phase 3:** barcha AI chaqiruvlari `AIOrchestrator.orchestrate()` orqali —
  Intent Router → Provider Chain (Gemini → Groq → OpenRouter → **MockProvider**)
  → `AIOutputValidator` → 1 martalik controlled retry → sanitizatsiya →
  fail-closed refund. Phase 4/5 `AIConcurrencyManager` (bounded queue) ham
  xuddi shu yo'ldan ishlaydi.
* **MockProvider kengaytmasi (additiv):** `context["smm_mode"]`
  (`VARIANTS | REPURPOSE | AUDIT | PLANNER`) bo'lgandagina yangi bank ishlaydi —
  eski `CREATE_POST / POST_AUDIT / GENERATE_VARIANTS` javoblari **o'zgarishsiz**
  (test 7 buni qo'riqlaydi).
* **Phase 2 kvota:** har bir **batch operatsiya uchun AYNAN BITTA** atomik bron
  (`services.ai_quota.reserve_ai_quota` → `database.reserve_ai_request`),
  ichki AI chaqiruvlari `skip_quota=True` + `db_module=False` — ya'ni
  5 variant/5 platforma uchun ham **1 kredit**. Operation turlari `AI_OPERATION_TYPES`
  oq ro'yxati doirasida: `magic_post:variants`, `magic_post:repurpose`,
  `post_score:audit`, `content_calendar:plan`.
  * rad etilgan kvota → AI'ga **bir ta ham** so'rov bormaydi (fail-closed);
  * DB xatosi → `QUOTA_UNAVAILABLE` + ruxsat yo'q;
  * AI natija bermasa (yoki reja uchun biror kunni ham boyitmasa) → bron
    **idempotent refund** qilinadi, `cost=0`;
  * auditning baholash qismi — **bepul** (`post_score` konventsiyasi),
    faqat «✨ yaxshilangan namuna» kredit sarflaydi.
* **Phase 2 sanitizer:** foydalanuvchiga chiqadigan har bir blokk
  `sanitize_html()` dan o'tadi. Qo'shimcha himoya — blok chunk'larga
  bo'lingandan **keyin ham** qayta sanitate qilinadi, shunda `<b>` bitta
  xabarda ochilib ikkinchisida qolmaydi (Telegram «can't parse entities»
  yo'q) va har bir xabar `html_length ≤ 4096`.

---

## 3. Test qamrovi — `tests/ai_advanced_features_test.py` (167 tekshiruv)

1. **Multi-variant** — 5 variant, to'g'ri uslub to'plami/tartibi, 10/10 juftlik
   farqli, hook/CTA/hashtag, premiumda chegirma toni yo'qligi, Telegram limiti;
2. **Repurpose** — 5 platforma va yuqoridagi barcha qat'iy struktura chegaralari,
   manba digesti (headline/punkt/CTA/havola);
3. **Audit** — 6 mezon, 1-10 oralig'i, og'irliklar yig'indisi 100, score
   qayta hisoblanadi, kuchli post > kuchsiz post, Top 3 raqamlangan va mezonlarga
   bog'langan, yaxshilangan namuna, determinizm, **ballar AI tomonidan
   o'zgartirilmaydi**, zararli kiritish escape, bo'sh matnda `INVALID_INPUT`;
4. **Reja** — 1/7/14/30 kun soni va maydon to'plami, ketma-ket kunlar/sanalar,
   format rotatsiyasi, PRO entitlement (`pro_required`), `invalid_duration`,
   AI javobidagi ortiqcha kunlar kesilishi, chunk chegaralari;
5. **Mock rejim** — `GEMINI/GROQ/OPENROUTER` kalitlari o'chirilganda to'rt
   xizmat ham 100% muvaffaqiyatli (`provider_used=Mock`), javoblar deterministik;
6. **Integratsiya** — 5 ta AI chaqiruvi uchun 1 bron, eski 2 qadamli zanjir
   ishlatilmasligi, fail-closed rad, refund hisobi, 1 kunlik reja va bepul audit
   bron qilmaydi, katta hajmda limit + teg muvozanati;
7. **Regressiya qo'riqonlari** — Intent Router, MockProvider eski javoblari,
   sanitizer limiti va idempotentligi, `database.reserve_ai_request/
   refund_ai_request` mavjudligi, `services.ai` eksportlari, `run_tests.sh`
   da yangi bosqichning ulanganligi.

Runner: `tests/run_tests.sh` → **`3u) 🚀 PHASE 11 & 12`** bosqichi qo'shildi;
`telegram_bot/tests/syntax_test.py` import ro'yxatiga 6 ta yangi modul kiritildi.

---

## 4. Xulosa

| Ko'rsatkich | Qiymat |
|---|---|
| `PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh` | **exit 0** |
| `[FAIL]` (butun suite) | **0** |
| Yangi test tekshiruvlari | **167 / 167 OK** |
| CI lint gate (`ruff`/`flake8` E9,F63,F7,F82) | **All checks passed** |
| API kalitsiz (mock) holatda yangi funksiyalar | **100% yashil** |

Yangi qatlam UI menyulariga tegmaydi (6-tugma menyu, submenu pariteti, i18n
sinxroni — barcha eski testlar o'zgarishsiz yashil). Handler'larga ulanish
(keyingi bosqich) uchun tayyor kirish nuqtalari:

```python
from services.ai import (generate_post_variants, repurpose_content,
                         audit_post, generate_content_plan)
```
