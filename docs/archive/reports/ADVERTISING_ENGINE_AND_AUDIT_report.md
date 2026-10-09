# 📢 FAZA 15 & 16 — REKLAMA DVIGATELI VA REKLAMA AUDITI

**Status:** ✅ Tayyor — barcha testlar yashil (`BASH EXIT CODE: 0`)
**Qamrov:** `telegram_bot/services/ads/` (yangi paket), `services/ai/smm_mock.py`
(ADS rejimi), `tests/advertisement_engine_and_audit_test.py` (yangi suite),
`tests/run_tests.sh` + `telegram_bot/tests/syntax_test.py` (ro'yxatga olish)

---

## 1. Muammo

Sotuv/reklama postlari agressiv, kanal ohangiga zid va — eng xavlisi —
**foydalanuvchi bermagan narx, kafolat, reyting yoki sertifikatlarni o'zidan
to'qib chiqaradigan** (hallucination) holatda generatsiya qilinayotgan edi.
Reklama chiqishidan oldin uni tekshiradigan sifat darvozasi yo'q edi.

## 2. Yechim — mavjud poydevor ustiga (noldan yozilmagan)

| Qatlam | Modul | Nima qiladi |
|---|---|---|
| Generatsiya | `services/ads/engine.py` | Brief → **4 xil** reklama varianti |
| Audit | `services/ads/audit.py` | 4 mezonli tekshiruv + nashr darvozasi |
| Zaxira bank | `services/ads/templates.py` | Deterministik, **raqamsiz** shablonlar |

Qayta ishlatilgan mavjud imkoniyatlar (yangi parallel tizim YO'Q):

* `services.ai.smm_common.SMMFeatureService` → **AIOrchestrator (Phase 3)**,
  Provider Chain, **Phase 2 atomik kvota** (butun batch uchun 1 bron),
  `sanitize_html` + 4096 chunk;
* `services.channels.dna` → `compute_channel_dna`, `get_channel_dna`,
  `build_dna_system_prompt`, `classify_emoji_level` — **Channel DNA**;
* `services.ai.audit.grade_for` → baho shkalasi (A+…E);
* `services.ai.smm_mock` → yangi `ADS` rejimi (offline/mock determinizm);
* `services.channels.team.ApprovalWorkflow` → admin tasdig'i holat mashinasi.

### 2.1 4 xil reklama formati

| # | Format | Burchak |
|---|---|---|
| 1 | 🧬 `native` | Kanalning **Channel DNA** ohangiga to'liq mos (uzunlik, emoji darajasi, CTA uslubi DNA'dan) |
| 2 | ⚡ `short` | 5 sekundda o'qiladi: hook + 1-2 fakt + bitta CTA (≤600 belgi) |
| 3 | 🎓 `educational` | Muammo → nega oddiy yechimlar ishlamaydi → yechim sifatida mahsulot |
| 4 | 🌿 `soft` | Qadriyatga asoslangan yumshoq taklif, bosimsiz CTA («shoshiling» taqiqlangan) |

Brief maydonlari: mahsulot nomi, faktlar ro'yxati, taklif/aksiya, maqsadli
auditoriya, CTA va havola. Validatsiya qat'iy: mahsulotsiz yoki faktsiz
reklama **yaratilmaydi**, `javascript:`/`data:` havolalari rad etiladi.

## 3. NO FABRICATION — uch qavatli himoya

1. **Prompt kontrakti** — faktlar «yagona ruxsat etilgan manba» sifatida
   beriladi; narx/kafolat/reyting/sertifikat taqiqlari aniq sanaladi; noma'lum
   ma'lumot uchun `[narx]` placeholder talab qilinadi (uz/ru/en).
2. **Chiqish filtri** — `strip_unsupported_claims()` har bir AI javobini
   faktlar korpusi bilan solishtiradi va faktlarda bo'lmagan da'voni **jumla
   darajasida olib tashlaydi** (`removed_claims` qayd etiladi). Model qanday
   bo'lishidan qat'i nazar ishlaydi.
3. **Zaxira yo'l** — AI javob bermaganda `templates.py` bankidagi
   deterministik, **raqamsiz** shablon ishlatiladi.

Ushlanadigan da'vo turlari: `price` (narx/foiz), `guarantee` (kafolat, «pul
qaytariladi»), `rating` (yulduz, «4.9», «№1»), `certificate` (sertifikat,
ISO, litsenziya), `statistic` («10 000+ mijoz»), `absolute` («eng yaxshi»),
`duration` (muddat). Sonlar normallashtiriladi: `120 000` == `120000`,
`1,500` ikki talqinda ham tekshiriladi — **soxta ogohlantirishlar (false
positive) minimallashtirilgan**: faktlarda BOR narx/muddat to'qima deb
hisoblanmaydi.

## 4. Reklama auditi (FAZA 16)

| Mezon | Og'irlik | Nima tekshiriladi |
|---|---|---|
| 🚫 Asossiz da'volar | 40 | faktlarda bo'lmagan narx/kafolat/reyting/sertifikat |
| 🧬 DNA mosligi | 20 | uzunlik, emoji darajasi, CTA uslubi, formatlash (Channel DNA) |
| 📣 CTA aniqligi | 20 | chaqiruv fe'li, oxirgi qatorlarda turishi, brief CTA/havolasi |
| 📖 O'qilishi | 20 | hajm (format bo'yicha), qator/jumla uzunligi, emoji spam, ALL CAPS |

* Ballar **deterministik va lokal** — model o'z reklamasiga «100/100» yoza
  olmaydi; kritik da'vo topilsa umumiy ball 40 dan yuqori chiqmaydi.
* DNA uchun yetarli post bo'lmasa mezon **SKIP** qilinadi — soxta baho yo'q
  (`Yetarli ma'lumot yo'q (kamida 5 ta post kerak)`).
* Kanal me'yoridan 2.6× uzun/qisqa post DNA bo'yicha oqmaydi (hajm — eng
  ko'zga tashlanadigan DNA belgisi).
* Hisobot Telegram HTML'da (`render_audit_report`), sanitize + limit bilan.

### Nashr darvozasi — FAIL-CLOSED

* `evaluate_publish(audit)` → muammo bo'lsa `allowed=False`,
  `requires_admin_approval=True`, sabablar (`UNSUPPORTED_PRICE`,
  `UNSUPPORTED_GUARANTEE`, `CTA_UNCLEAR`, …) va tushunarli xabar.
* Admin tasdiqlasa → `allowed=True` + `approved_by` qayd etiladi.
* Audit yo'q/bajarilmagan bo'lsa → **admin tasdig'i bilan ham** nashr to'siladi.
* `gate_with_workflow()` auditni mavjud `ApprovalWorkflow` ga ulaydi: muammoli
  reklama `pending_approval` ga tushadi va admin `approve()` qilgunicha
  `schedule()`/`publish()` **ishlamaydi** (state machine bosqich o'tkazmaydi).

## 5. Testlar

`tests/advertisement_engine_and_audit_test.py` — **241 ta tekshiruv**, 6 bo'lim:

1. **4 format** — soni, tartibi, farqliligi (sinonim emas), CTA/havola,
   brief validatsiyasi, format tanlash, HTML muvozanati, 4096 limiti;
2. **NO FABRICATION** — to'qimachi AI simulyatsiyasi: 14 ta to'qima da'vo
   ushlanadi va postga **tushmaydi**; faktlarda bor narx to'qima emas;
   fallback shablonlar raqamsiz; mock rejim toza;
3. **Audit** — toza vs to'qima reklama, 4 mezon, determinizm, CTA/o'qilish/
   DNA metrikalari, hisobot;
4. **Nashr darvozasi** — bloklash, admin tasdig'i, `ApprovalWorkflow`
   integratsiyasi, end-to-end oqim;
5. **Poydevor** — 4 AI chaqiruvi uchun 1 atomik bron, kvota rad etilsa AI'ga
   chiqilmasligi, DB xatosida fail-closed, AI yiqilsa refund, Channel DNA
   ulanishi, sanitizer/chunk;
6. **Regressiya** — eksportlar, mock `ADS` rejimi (mavjud VARIANTS/AUDIT
   buzilmagan), uz/ru/en paritet, kvota oq ro'yxati, runner ro'yxati.

```bash
PYTHON=/tmp/venv/bin/python bash tests/run_tests.sh
echo "BASH EXIT CODE: $?"
# → BARCHA TESTLAR 100% YASHIL ✔
# BASH EXIT CODE: 0
```

## 6. Keyingi qadam (ushbu sprint qamrovidan tashqari)

Xizmat qatlami tayyor; admin panel/menyu tugmalari («📢 Reklama yaratish»,
variant tanlash va tasdiqlash ekrani) handler qatlamiga keyingi sprintda
ulanadi. `AdEngine.generate()` / `audit_ad()` / `evaluate_publish()`
API'si handler uchun tayyor.
