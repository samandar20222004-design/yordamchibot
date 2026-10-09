# 🧠 CHANNEL INTELLIGENCE REPORT — Channel DNA, izohlar klasteri va reklamalar

> **Holat:** ✅ PASS — `tests/channel_intelligence_dna_test.py` (PHASE B),
> `tests/production_safety_and_channel_intelligence_base_test.py`,
> `tests/channel_comments_and_advisor_test.py`,
> `tests/advertisement_engine_and_audit_test.py` (FAZA 15/16) — barchasi
> yashil, **BASH EXIT CODE: 0**.
> **Modullar:** `telegram_bot/services/channels/` — `dna.py`, `monitor.py`,
> `monitoring.py`, `best_time.py`, `comments.py`, `advisor.py`,
> `weekly_report.py`, `team.py`, `duplicate_detector.py`, `recycle.py`;

---

## 1. Channel DNA — uslubiy profil (`services/channels/dna.py`)

Kanal postlari kuzatuvi (`channel_post_events`, **idempotent event
ingestion** — bir xil event ikki marta hisoblanmaydi) asosida profil
hisoblanadi va `channel_intelligence_profiles` / `channel_dna`
jadvaliga **UPSERT** qilinadi:

- Asosiy metrikalar: `average_post_length`, `emoji_level`
  (kam/o'rtacha/ko'p), `cta_style`, `formatting_style`, `sample_size`,
  `confidence_score`.
- FAZA 8/9/22 kengaytmasi: `language`, `tone`, `topics`, `avg_length`,
  `emoji_density`, `best_hours`, `best_weekdays`,
  `high_performing_formats` — har biri `sample_size`, `confidence`
  (0.0–1.0) va `updated_at` bilan.
- **Soxta raqam taqiqi:**
  * 5 tadan kam post bo'lsa — profil hisoblanmaydi: `confidence='low'` +
    "Yetarli ma'lumot yo'q (kamida 5 ta post kerak)" holati;
  * kichik sample'da PAST confidence — uydirma yuqori ishonch yo'q.
- AI orkestrator generatsiyada (kontekstda `channel_id` bo'lsa VA kanal
  aynan shu foydalanuvchiniki bo'lsa — **IDOR himoyasi**) DNA ixcham
  system-prompt bloki sifatida ulanadi.
- Barcha hisob funksiyalari **PURE** (DB'siz) — deterministik, testlanadi.

## 2. Smart Best Time (`best_time.py`)

- Eng yaxshi vaqt taklifi faqat **haqiqiy kuzatuv** metrikalaridan —
  ma'lumot yetishmasa soxta "18:00 eng yaxshi" kabi raqamlar
  qaytarilmaydi (bo'sh/izohli holat).
- Haftalik hisobot (`weekly_report.py`): har dushanba 09:00 (Toshkent),
  FAQAT kanal egasining shaxsiy chatiga — ixcham, ehtiyotkor advisor
  matni ("taxminiy" deb belgilangan).

## 3. Izohlar klasteri (`services/channels/comments.py`)

**Comment → Content** dvigateli, maxfiylik-first dizayn:

- Xom izohlar FAQAT xotirada tahlil qilinadi; ixtiyoriy persistence hook
  faqat **kompozit hash + agregat hisoblagichlar**ni saqlaydi — izohchi
  ID, username, telefon, email, URL yoki xom matn HECH QACHON yozilmaydi
  (bot shaxsiy ma'lumot arxiviga aylanmaydi).
- Sanitizatsiya: email/URL/telefon/@handle/raqamlar maskalanadi,
  keyin mavzu-tokenlar klasterlanadi (takroriy savollar ustiga
  kontent-g'oyalar).
- `channel_comments_and_advisor_test.py` — PASS.

## 4. Reklamalar (FAZA 15/16 — `services/ads/`)

- **Reklama dvigateli:** bitta briefdan AYNAN 4 variant — 🧬 native
  (Channel DNA ohangiga mos), ⚡ short, 🎓 educational, 🌿 soft;
  brief validatsiyasi (mahsulotsiz/faktsiz reklama yaratilmaydi, xavfli
  havola rad etiladi — FAZA 23 SSRF qatlami bilan bir siyosatda).
- **NO FABRICATION:** AI narx, chegirma (%), kafolat («100%»), reyting
  (4.9, №1), sertifikat (ISO) yoki statistika (10 000+ mijoz) to'qisa —
  bu da'volar POSTGA TUSHMAYDI (jumla darajasida olib tashlanadi,
  `removed_claims` qayd etiladi). Fallback shablonlar ham raqamsiz.
- **Reklama auditi (4 mezon):** 🧬 DNA mosligi, 📣 CTA aniqligi,
  🚫 asossiz da'volar, 📖 uzunlik/o'qilish — ballar deterministik (model
  o'z reklamasiga "100/100" yoza olmaydi); DNA yetarli bo'lmasa mezon
  SKIP (soxta baho yo'q).
- **Nashr darvozasi (fail-closed):** audit muammoli bo'lsa reklama ADMIN
  tasdig'isiz chiqmaydi; admin tasdigi `approved_by` bilan izlanadi;
  audit yo'q bo'lsa — admin tasdig'i ham to'siladi.

## 5. Xavfsizlik va izolyatsiya (FAZA 23 bilan yangilangan)

- Barcha kanal ichki amallarida **server-side egalik tekshiruvi**
  (begona kanal paneli/DNA/best-time ochilmaydi — fail-closed, aniq
  lokalizatsiyalangan xabar).
- FAZA 23: `pending.py` tahrirlash callback'lari ham shu sinfdagi
  himoyaga qo'shildi (post ID → egalik guard'i, DB xatosida ham rad).
- Monitoring/poll ishlar (`scheduler.poll_content_sources_job` va boshq.)
  hech qachon istisno tashlamaydi; FAZA 25 fon-vazifa chegaralari
  resurs sizishini bloklaydi.

## 6. Test xulosasi

| Suite | Natija |
|---|---|
| `tests/channel_intelligence_dna_test.py` (ingestion, DNA UPSERT, best-time, IDOR) | ✅ PASS |
| `tests/production_safety_and_channel_intelligence_base_test.py` | ✅ PASS |
| `tests/channel_comments_and_advisor_test.py` | ✅ PASS |
| `tests/advertisement_engine_and_audit_test.py` (4 variant, no-fabrication, audit, nashr darvozasi) | ✅ PASS |
| `tests/ai_engine_v2_test.py` (REASONING lane — kanal tahlili/DNA marshruti) | ✅ PASS |

**XULOSA: Channel Intelligence (DNA + izohlar + reklama) — PASS ✅**
