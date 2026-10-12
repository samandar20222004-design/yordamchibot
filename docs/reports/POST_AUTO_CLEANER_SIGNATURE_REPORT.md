# 🧹 POST AUTO-CLEANER & CUSTOM SIGNATURE — Nested «Ko'proq sozlamalar»

**Sana:** 2026-10-12
**Status:** ✅ Bajarildi — `bash tests/run_tests.sh` exit 0
**Tarmoq:** `telegram_bot/` (PTB + PostgreSQL), `tests/`

---

## 1. Nima o'zgardi (qisqacha)

| Talab | Yechim |
|---|---|
| Funksiya **NESTED** «Sozlamalar → Ko'proq sozlamalar» ichida | ⚙️ Sozlamalar hub'i **10 tugma bo'lib QOLDI**; yo'l: ✍️ Post sozlamalari → **⚙️ Ko'proq** → **🧹 Avto-tozalash** |
| Foydalanuvchi o'z havolasi/imzosini saqlaydi | FSM (1 holat) + `users.post_signature_text VARCHAR(255)`; [✍️ Imzo] [🗑 Imzoni o'chir] [🧪 Namuna] |
| Begona `@username` + footer reklama qatorlari o'chadi | `services/post_cleaner.py` — **ENTITY-SAFE** dvigatel (regex + prefix-sum offset xaritasi) |
| Formatlash daraxti 100% saqlanadi | 3 adapter: **HTML** / **Telegram MessageEntity** / **Markdown** ↔ yagona yadro modeli |
| Mavjud testlar 100% yashil, layout buzilmaydi | 0 ta mavjud test tahrirlandi; hub 10 tugma / 5 qator × 2 saqlandi |
| Ko'p davlatlilik | Reklama naqshlari uz/ru/en; **mamlakat cheklovi YO'Q**; yangi til = yangi kalit so'z |

**Yangi fayllar:** `telegram_bot/services/post_cleaner.py` (1225 qator),
`telegram_bot/utils/post_signature.py` (66), `tests/post_auto_cleaner_test.py` (945).
**O'zgargan:** 11 fayl, +940 / −11.

---

## 2. Nega joylashuv SHUNDAY (muhim arxitektura qarori)

Topshiriq «Ko'proq sozlamalar» menyusini mavjud deb hisoblagan; **repo'da bunday
menyu yo'q edi**. Uni yaratish kerak edi, lekin ⚙️ Sozlamalar hub'i **12+ test
fayli** bilan qat'iy qo'riqlanadi:

| Test | Talab |
|---|---|
| `settings_hub_cleanup_1qadam_test` | `len(cbs) == 10` |
| `ui_ux_and_navigation_standards_test` | 10 tugma / 5 qator, **har birida aynan 2 ta** |
| `final_acceptance_suite_test`, `postassist_polish_test`, `settings_and_stats_v2_test`, `unit_test`, `refactor_step3_test`, `manual_posting_and_unified_menu_test`, `new_requirements_test`, `account_settings_i18n_test`, `i18n_ai_parity_test`, `main_menu_and_dna_onboarding_test`, `support_ticket_flow_test`, `privacy_and_data_deletion_test` | aniq callback **tartibi** |

Shu sababli yangi tugma hub'ga **qo'shilmadi** — bo'lim chuqurroqqa joylashtirildi:

```
⚙️ Sozlamalar (hub — 10 tugma, O'ZGARMAGAN)
  └── ✍️ Post sozlamalari (stgs_post)
        [✅ Suv belgisi] [⬜️ Muallif imzosi]
        [◀️ Orqaga]      [⚙️ Ko'proq]        ← YANGI (Orqaga BIRINCHI tugma)
              └── ⚙️ Ko'proq sozlamalar (stgs_more)     ← YANGI nested menyu
                    └── 🧹 Avto-tozalash (stgs_clean)   ← YANGI funksiya
                          [✅/⬜️ Avto-tozalash]
                          [✅/⬜️ @ Eslatmalar] [✅/⬜️ 🔗 Havolalar]
                          [✅/⬜️ 📢 Reklama]   [✍️ Imzo]
                          [🧪 Namuna]         [🗑 Imzoni o'chir]
                          [◀️ Orqaga → stgs_more]
```

`post_rows[1][0][0] == "◀️ Orqaga"` kontrakti saqlanadi (yangi tugma qatordagi
**IKKINCHI** o'rinda). 🔔 Bildirishnomalar ekranida [⚙️ Ko'proq] **yo'q**.

---

## 3. Entity-safe tozalash — nega oddiy regex YETMAYDI

Telegram posti = matn **+ formatlash daraxti**. Oddiy `re.sub` bilan:

* `<a href="...">t.me/x</a>` → **bo'sh** `<a></a>` qoladi;
* entity offset'lari siljiydi → bold **boshqa so'zga** tushadi;
* Telegram `MESSAGE_ENTITIES_INVALID` qaytaradi.

### 3.1 Yechim: prefix-sum offset xaritasi

O'chirishlar avval **hisoblanadi**, so'ng har bir bosqich o'z xaritasini
qaytaradi va span'lar ketma-ket qayta xaritalanadi:

```
matn ──(1) o'chirish niqobi──▶ prefix₁ ──▶ span'lar qayta hisoblandi
     ──(2) bo'shliq kollapsi──▶ prefix₂ ──▶ span'lar YANA qayta hisoblandi
```

**Qoida:** matn ustida hech qanday "keyingi" regex tuzatishi prefix'siz
bajarilmaydi. Shu sababli offset'lar hech qachon siljimaydi va "yetim"
(matnsiz) formatlash qolmaydi.

Span `[start, end)` → `[prefix[start], prefix[end])`:

| Holat | Natija |
|---|---|
| butunlay o'chirilgan | span **tushirib qoldiriladi** |
| qisman o'chirilgan | span **qirqiladi** |
| tegilmagan | offset siljimaydi |

### 3.2 Uch adapter

| Format | Kirish | Chiqish |
|---|---|---|
| **HTML** | `sanitize_html` bilan balanslanadi → stack parser | kanonik Telegram HTML (`<b>/<i>/<u>/<s>/<tg-spoiler>/<a>/<code>/<pre>/<blockquote>`) |
| **MessageEntity** | UTF-16 offset → Python indeksi | PTB `MessageEntity` (yoki bir xil shartnomadagi `dict`) |
| **Markdown** | `**bold**` `__italic__` `~~s~~` `||spoiler||` `` `code` `` `[t](u)` | belgilar juft yopiladi |

`<pre><code class="language-x">` juftligi bitta `pre` span'ga birlashtiriladi
(til saqlanadi); `blockquote expandable` va `custom_emoji_id` ham saqlanadi.

### 3.3 Nima o'chadi

| Qatlam | Qoida |
|---|---|
| **Mention** | `@username` (5..32, harf bilan) — email (`a@b.com`) va **o'z kanali** bundan mustasno |
| **Havola** | `t.me` / `telegram.me` / `telegram.dog` (+ `joinchat`) — o'z kanali bundan mustasno |
| **Reklama (kuchli)** | `Reklama:` / `Manba:` / `Source:` / `via` / `©` / faqat havolali qator — **matndagi o'rnidan qat'i nazar** |
| **Reklama (footer)** | oxirgi ~25% (bo'sh bo'lmagan) qator + kalit so'z + **kamida 3 qator** |
| **Pointer-shell** | qator deyarli faqat begona pointer + atributsiya marker'i («orqali», «источник», «via») |

**Himoyalar:**

* `code` / `pre` ichidagi matn **HECH QACHON** tozalanmaydi (LITERAL);
* kamida-3-qator sharti tufayli 1–2 qatorli post «footer» deb **butunlay
  o'chirilmaydi** (bu xato ishlab chiqishda topildi va tuzatildi);
* pointer-shell qoidasi atributsiya **marker'ini** talab qiladi — shu sababli
  `"Salom @x dunyo"` saqlanadi, `"📢 @source_news orqali tarqatildi"` o'chadi;
* tozalash natijasi bo'sh bo'lsa → **asl matn** qaytariladi (fail-safe).

---

## 4. ✍️ Custom Signature

* **Saqlash:** FSM `CLEANER_SIGNATURE_INPUT = 545` (1 holat) →
  `users.post_signature_text`.
* **Normalize (yagona manba):** `utils/post_signature.py` — boshqaruv/yo'nalish
  belgilari (NUL, ESC, RTL/LRM/RLM) o'chadi, ≤3 qator, ≤255 belgi.
  `utils` — namespace package (`__init__.py` yo'q), shu sababli
  `repositories` → `services` import **sikli yo'q**.
* **URL imzo** → `<a href>` (`utils.security.validate_button_url` orqali;
  `javascript:` rad etiladi).
* **Yozuvcha imzo** → HTML-escape (`<script>` teg bo'lib ishlamaydi).
* **Idempotent:** imzo matnda allaqachon bo'lsa dublikat qo'shilmaydi.

---

## 5. 🌍 Ko'p davlatlilik tekshiruvi (2-band)

| Tekshiruv | Natija |
|---|---|
| Yangi matnlar lokalizatsiyasi | `settings_stats_parity_report()` → **113 kalit, `in_sync=True`**, `missing`/`extra`/`format_mismatch`/`empty` bo'sh |
| 18-belgi standarti | yangi 5 inline yorliq × 3 til = 15/15 ≤18 (`ss_btn_more` 10/6/7, `ss_btn_cleaner` 15/13/12, ...) |
| Qo'llab-quvvatlanmagan til kodlari | `fr, de, ja, kz, tr, '', None, 'UZ', 'en-US'` — 9/9 **crash'siz** (uz'ga fallback) |
| Mamlakat cheklovi | yangi kodda **YO'Q** (`grep` toza). TEST 5 da `de/jp/br/uz/us` manbalari **bir xil** tozalanadi |
| Kalendar | `resolve_country`: `UZ/JP/DE/BR/US` → o'z kodi; `uzbekistan`/`ozb` → `UZ`; `global` → `''`; noma'lum `xx` → `XX`; bo'sh/`None` → `UZ` (fail-safe) |
| Buyruqlar | yangi buyruq **qo'shilmadi** (faqat inline callback + 1 FSM holati) |
| AI prompt shablonlari | **qo'shilmadi** — tozalash deterministik (AI'siz), shu sababli prompt tili muammosi yo'q |

Reklama kalit so'zlari uz/ru/en uchalasida berilgan va ro'yxat
**KENGAYTIRUVCHAN**: yangi til = yangi kalit so'z, kod o'zgarmaydi.

---

## 6. 📥 Ingest ulanmasi

Tozalash **MANBADA** (AI/digest'dan **OLDIN**) bajariladi — shu sababli botning
o'z qo'shadigan yorliqlari (`🔗 Manba:`, `👉 Batafsil`) hech qachon
o'chirilmaydi, faqat **TASHQI** manbaning reklama/atributsiya qatorlari ketadi.

| Manba | Ulanma | Konfiguratsiya |
|---|---|---|
| 📡 RSS/ATOM | `RssService.build_draft` (`_clean_feed_item`) | `check_source` da **BIR MARTA** o'qiladi, N elementga uzatiladi (N×2 DB so'rovi yo'q) |
| 🔗 URL → post | `UrlPostService.build_drafts` (`_clean_source_article`) | faqat `title`/`text`; **META** (`source`/`url`) saqlanadi |
| 📢 Kanal-extract | `_adapt_post_with_ai` + `_apply_auto_cleaner` | mavjud `_clean_foreign_content` dan **keyin** opt-in pass |

**Standart O'CHIRILGAN (opt-in):** `post_auto_clean = False`. Mavjud
foydalanuvchilar uchun hech narsa o'zgarmaydi (regressiya yo'q).
Barcha ulanmalar **fail-soft**: DB/xato bo'lsa asl matn qaytadi.

---

## 7. Ishlab chiqishda topilgan va TUZATILGAN xatolar

| # | Xato | Tuzatish |
|---|---|---|
| 1 | 1–2 qatorli post «footer» deb **butunlay** o'chib ketardi (yagona qator o'zi footer edi) | footer mintaqasi **bo'sh bo'lmagan** qatorlar bo'yicha + kamida 3 qator sharti |
| 2 | `_apply_removals` dan keyingi `re.sub` kollapsi offset'larni **siljitib** yuborardi | kollaps ham niqob + prefix qaytaradi; span'lar **ikki marta** qayta xaritalanadi |
| 3 | Markdown rekursiyasi `base + len(parts)` bilan pozitsiyani **ikki marta** sanardi | `length()` mutlaq uzunlikka o'tkazildi, `walk` qo'shilgan belgilar sonini qaytaradi |
| 4 | `_close_tag` da `LINK` tarmog'i yo'q edi → `KeyError: 'link'` | `</a>` qo'shildi |
| 5 | `"📢 @source_news orqali tarqatildi"` → `"📢 orqali tarqatildi"` qoldig'i | **pointer-shell** qoidasi (atributsiya marker'i talabi bilan) |
| 6 | `CLEANER_SIGNATURE_INPUT = 530` — `handlers/sources.py` dagi `SRC_HUB = 530` bilan **to'qnashdi** | **545** ga ko'chirildi (530–539 manbalar bloki band) |
| 7 | `_normalize_post_signature` facade'da yo'q edi (`repository_layering_test`) | `database.py` eksportiga qo'shildi |

---

## 8. Testlar

**Yangi suite:** `tests/post_auto_cleaner_test.py` — **281 tekshiruv, 0 xato**.

| # | Bo'lim | Qamrov |
|---|---|---|
| 1 | Entity-safe HTML | `<b>/<i>/<a>` saqlanadi, **XML simulyatsiyasi** bilan yaroqlik, yetim teg yo'q |
| 2 | MessageEntity | UTF-16 offset (emoji = 2 birlik), to'liq/qisman o'chirish, `code`/`pre` himoyasi, `language` |
| 3 | Markdown | belgilar daraxti juft yopiladi |
| 4 | Signature | oxir/bosh, URL→`<a>`, **XSS escape**, `javascript:` rad, idempotent, normalize |
| 5 | Ko'p davlatlilik | uz/ru/en naqshlari + `de/jp/br/uz/us` manbalari bir xil |
| 6 | Fail-safe | opt-in, bo'sh natija → asl matn, o'z kanali, email, `None`/bo'sh kirish |
| 7 | Navigatsiya | hub 10 tugma / 5×2, `[⚙️ Ko'proq]` joyi, `stgs_more` menyusi, registry |
| 8 | Handler routing | `stgs_more`/`stgs_clean`/`stgs_clean_demo`/`stgs_clean_sig_clear` + **OQ RO'YXAT fail-closed** |
| 9 | Imzo saqlash | yagona normalize qoidasi, schema ↔ migration ↔ facade pariteti |
| 10 | i18n | 113 kalit paritet + 18-belgi standarti + toggle yorliqlari 3 tilda |
| 11 | Ingest | RSS/URL/kanal-extract — yoqilgan/o'chirilgan holatlar, bot yorlig'i saqlanadi |

**Regresiya:** `bash tests/run_tests.sh` → **exit 0** (0 FAIL). Suite
`tests/run_tests.sh` ga 🌍 kalendar bosqichidan keyin qo'shildi.

---

## 9. Fayllar

**Yangi**

| Fayl | Vazifa |
|---|---|
| `telegram_bot/services/post_cleaner.py` | entity-safe tozalash dvigateli (yadro + 3 adapter + siyosat + DB yordamchilari) |
| `telegram_bot/utils/post_signature.py` | imzo normalizatsiyasi (bog'liqliksiz, yagona manba) |
| `tests/post_auto_cleaner_test.py` | 281 tekshiruvlik suite |

**O'zgargan**

| Fayl | O'zgarish |
|---|---|
| `handlers/settings.py` | nested ⚙️ Ko'proq + 🧹 cleaner ekranlari, `clean` scope, FSM handlerlari (+437) |
| `translations/settings_stats.py` | 27 × 3 til = 81 yangi i18n kalit (+183) |
| `repositories/users_repository.py` | `get/set_user_post_signature` (+76) |
| `database.py` / `schema.sql` | `post_signature_text` ustuni + idempotent migratsiya + facade |
| `handlers/__init__.py` | FSM holati 545 + `^stgs_clean_sig$` entry point |
| `keyboards/callback_data.py` | 5 yangi aniq callback tokeni |
| `services/sources/rss_service.py` | `_clean_feed_item` + batch konfiguratsiya |
| `services/sources/url_extractor.py` | `_clean_source_article` |
| `handlers/channel_extract.py` | `_apply_auto_cleaner` (opt-in pass) |
| `tests/run_tests.sh` | yangi suite bosqichi |
