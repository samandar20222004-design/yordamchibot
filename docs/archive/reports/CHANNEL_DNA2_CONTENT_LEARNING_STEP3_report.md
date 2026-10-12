# 🧬 STEP 3 — CHANNEL DNA 2.0 & CONTENT LEARNING INTEGRATION

> **Holat:** ✅ PASS — `bash tests/run_tests.sh` (to'liq regressiya +
> yangi `tests/channel_dna2_content_learning_test.py`, 145 tekshiruv) —
> **0 FAIL, BASH EXIT CODE: 0**.
> **Modullar:** `telegram_bot/services/channels/dna.py` (DNA 2.0),
> `telegram_bot/services/channels/content_learning.py` (yangi),
> `telegram_bot/translations/content_learning.py` (yangi),
> `telegram_bot/handlers/ai_assistant.py` (AI Studio/Audit ekranlari),
> `telegram_bot/handlers/sources.py` + `telegram_bot/handlers/channels.py`
> (generatsiya promptlari), `telegram_bot/services/channels/__init__.py`.

---

## 1. 🧬 Channel DNA 2.0 — generatsiya promptlariga avtomatik integratsiya

Post generatsiya promptlari endi kanal profilini **AVTOMATIK** hisobga
oladi (`build_dna_prompt_2` — legacy `build_dna_system_prompt` kontrakti
100% saqlangan holda, ustiga 4 ta yangi bo'lim):

| Bo'lim | Manba (faqat REAL ma'lumot) | Misol (uz) |
| --- | --- | --- |
| **Ohang (tone)** | `channel_dna.tone` / extended profil tasnifi | `Ohang: do'stona — post davomida SAQLANG.` |
| **Uzunlik afzalligi** | `average_post_length` (kuzatilgan o'rtacha) | `Uzunlik afzalligi: ~450 belgi (±20%)` |
| **CTA uslubi** | `cta_style` (always/most/sometimes/none) | `CTA uslubi: har postda CTA. Har postda ANIQ bitta CTA ishlating…` |
| **Lug'at cheklovlari** | `language` + `tone` + `topics` | `LUG'AT CHEKLOVLARI: til — o'zbek; samimiy, sodda so'zlar…; kanal mavzulariga yaqin so'zlar: futbol…` |

Qat'iy qoidalar:

- **NO FABRICATION:** bo'lim faqat real profil maydoni mavjud bo'lganda
  qo'shiladi (legacy profilda `tone` yo'q → tone bo'limi UYDIRILMAYDI);
  `sample_size < 5` bo'lsa butun blok BO'SH (eski kontrakt).
- **Profil normalizatsiyasi:** `normalize_dna_profile` uchala shaklni
  birlashtiradi — legacy `channel_intelligence_profiles` qatori,
  `compute_channel_dna_extended` profili (o'ralgan metrikalar) va
  `channel_dna` flat qatori (JSONB `profile` bilan).
- **Prioritet:** `attach_dna_to_context` endi avval KENGAYTIRILGAN
  `channel_dna` profilini (tone/language/topics bilan), bo'lmasa legacy
  profilni o'qiydi.

### Graceful fallback (tahlil qilinmagan kanal)

DNA hali tahlil QILINMAGAN (profil yo'q yoki yupqa) kanal uchun
`build_default_tone_prompt(lang)` — standart ohang bloki (uz/ru/en)
qo'shiladi: **xatosiz**, **soxta metrikasiz**, `ctx["channel_dna_default_tone"]=True`
flagi bilan. IDOR kontrakti saqlanadi: **begona kanal** uchun kontekst
umuman O'ZGARMAYDI (fallback ham ulanmaydi); `skip_dna` va `channel_id`
bo'lmaganda xuddi shunday. DB xatosida fail-soft (generatsiya to'xtamaydi).

### Ulangan generatsiya yo'llari

- `services/ai/orchestrator.py` → `attach_dna_to_context` (barcha
  orchestrator-driven SMM xizmatlari: variants, repurpose, planner, audit…);
- `handlers/sources.py::_dna_block` (URL→post, RSS avtopublish) — DNA 2.0;
- `handlers/channels.py::_dna_prompt_block` (bepul namunaviy qoralama) —
  DNA 2.0 + til (uz/ru/en) endi `lang` bo'yicha lokal.

## 2. 📚 Content Learning & Gap Detection (AI Studio / Audit ekranlari)

Yangi PURE xizmat `services/channels/content_learning.py`:

- 8 ta kanonik format: ❓ **Q&A**, 🎓 **tutorial**, ⭐ **social proof**,
  📰 news, 💡 tips, 📊 poll, 🛒 offer, 📖 story — AI'siz, deterministik
  kalit-so'z tasnifi (uz/ru/en o'zaklari);
- `analyze_content_coverage(posts)` — REAL post matnlari
  (`channel_posts_history`) bo'yicha kuzatilgan formatlar, yetishmayotgan
  formatlar (gaps) va ustuvor tavsiyalar (Q&A → tutorial → social proof
  birinchi navbatda, ≤4 ta);
- **NO FABRICATION:** postlar < 5 → `insufficient=True`, tavsiyalar BO'SH,
  halol xabar real `{n}/{min}` sonlari bilan; kanal ulanmagan →
  `reason="no_channels"` (ochiq ko'rsatma); juda qisqa matnlar (<20
  belgi) hisoblanmaydi;
- **IDOR:** `get_content_learning_for_user` faqat `db.get_user_channels`
  qaytargan O'Z kanallarini tahlil qiladi; DB xatosida fail-soft
  (`ok=False`, istisno yo'q).

### UI integratsiya (lokalizatsiya qilingan)

- **AI Studio hub** (`ai_studio_hub_entry`): menyu matniga `📚 KONTENT
  O'RGANISH` bloki qo'shiladi — tahlil qilingan post/kanal soni (real),
  kuzatilgan formatlar, yetishmayotgan formatlar bo'yicha aniq tavsiyalar;
  ma'lumot yo'qda HALOL eslatma (upgrade/analiz triggeri). Klaviatura va
  FSM kontrakti O'ZGARMAGAN (7 tugma, `AI_MENU_STATE`, bitta xabar).
- **Post auditi** (`ai_audit_received`): audit natijasiga tavsiyalar bloki
  FAQAT aniq tavsiyalar mavjud bo'lganda qo'shiladi (`require_reco=True`) —
  ma'lumot yo'qda audit toza qoladi; Telegram 4096 chegarasi himoyasi
  (audit matni 3500→2600 ga kichrayadi, blok 1200 gacha).
- Barcha matnlar `translations/content_learning.py` (yangi i18n moduli,
  `content_menu.py` konvensiyasi) orqali — **UZ/RU/EN 100% paritet**
  (`content_learning_parity_report().in_sync == True`, 26 kalit).

## 3. 🌍 Trilingual parity (UZ/RU/EN)

- DNA 2.0 prompt shablonlari (`_DNA2_SECTION_TEMPLATES`), tone/CTA/lug'at
  qoidalari (`DNA_TONE_LABELS`, `CTA_STYLE_INSTRUCTIONS`,
  `VOCABULARY_RULES`, `DNA_LANGUAGE_NAMES`) va standart ohang fallback
  (`DEFAULT_TONE_PROMPTS`) — uchala tilda;
- Kontent o'rganish xato/upgrade xabarlari (`cl_insufficient`,
  `cl_no_channels`) va barcha tavsiyalar (`cl_reco_*`) — uchala tilda;
  noma'lum til → `uz` fallback (xatosiz);
- Paritet test darajasida qo'riqlanadi: kalitlar to'plami + format
  argumentlari (`{n}`, `{min}`, `{channels}`, `{count}`) uz↔ru↔en bir xil.

## 4. ✅ Testlar

- **Yangi:** `tests/channel_dna2_content_learning_test.py` — 8 ta TEST
  bloki, **145 tekshiruv, 0 FAIL**: DNA 2.0 builder (3 til + flat row +
  NO FABRICATION), default tone fallback, `attach_dna_to_context`
  (owner/IDOR/skip_dna/thin/extended-prioritet/fail-soft), orkestrator
  end-to-end, content learning PURE funksiyalari, render + i18n paritet,
  service IDOR, AI Studio/Audit handler integratsiyasi (haqiqiy handler +
  soxta DB).
- **Regressiya:** `bash tests/run_tests.sh` — mavjud suite'lar 100% yashil
  (legacy DNA kontraktlari: `"KANAL USLUBI (DNA)"`, `"450 belgi"`,
  IDOR `not in` tekshiruvlari, studio klaviatura 7 tugma, i18n paritet
  auditlari — barchasi saqlangan).
