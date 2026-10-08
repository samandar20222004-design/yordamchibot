# 🎨 REAKSIYALAR · ✏️ TAHRIRLASH MENYUSI · ❌ BEKOR QILISH · 💡 AI ESLATMA · 📸 VISION — 5 TA TUZATISH

**Sana:** 2026-10-08
**Branch:** `arena/0432f206-yordamchibot`
**Test qo'riqoni:** `tests/reactions_edit_cancel_vision_flow_test.py` (96 tekshiruv)
**To'liq regressiya:** `bash tests/run_tests.sh` → 100% YASHIL (0 FAIL)

---

## 0. Topshiriqdagi yo'llar ⇄ repo'dagi haqiqiy modullar

Topshiriqda ko'rsatilgan fayllar repo strukturasida quyidagi modullarga mos keladi
(loyihada FSM/handler modullari shu nomlar bilan yashaydi):

| Topshiriqda | Repo'da (haqiqiy manba) |
| --- | --- |
| `telegram_bot/handlers/reactions.py` | `telegram_bot/handlers/manual_post.py` (❤️ reaksiyalar oqimi) + `telegram_bot/keyboards/inline.py` (`get_manual_reaction_keyboard`, `split`/normalizatsiya) + `telegram_bot/translations/manual_post.py` (matnlar) |
| `telegram_bot/handlers/scheduled_posts.py` | `telegram_bot/handlers/pending.py` (tahrirlash oqimlari: `p_edit:` / `p_time:` / `p_btn:` / `p_react:`) + `telegram_bot/handlers/queue.py` (📅 Rejalashtirilgan ro'yxati) + `telegram_bot/handlers/start.py` (`cancel_handler`) |
| `telegram_bot/services/ai/prompts.py` | `telegram_bot/services/ai/prompts.py` (aynan mavjud) |
| `telegram_bot/services/ai/vision.py` | `telegram_bot/utils/vision_analyzer.py` (Vision AI yadrosi) + `telegram_bot/handlers/image_post.py` (rasm → post UI) + `telegram_bot/services/ai_service.py` (generation prompti) |

---

## 1. 🎨 REAKSIYA EMOJILARINI ERKIN KIRITISH

**Fayl:** `telegram_bot/translations/manual_post.py`, `telegram_bot/handlers/manual_post.py`

* «➕ O'zim kiritaman» endi AYNAN topshiriqdagi ko'rsatmani chiqaradi:

  > Post ostida chiqadigan emojilarni oralariga bo'sh joy (probel) tashlab yuboring (5 tagacha). Masalan: 🔥 ❤️ 👍 🎉

  Matn uz/ru/en — uchala tilda (`mp_react_custom_prompt`), eski «10 tagacha»
  cheklovi matndan olib tashlandi (`mp_react_custom_invalid` ham yangilandi).
* Yangi yordamchi `split_custom_reaction_emojis(text, max_count=5)`:
  * matn **probel** (`str.split()`) bo'yicha ajratiladi;
  * faqat emoji tokenlar olinadi, takrorlar (variation selector hisobga
    olinmasdan) olib tashlanadi;
  * natija **5 tagacha** kesiladi va kiritish tartibi saqlanadi;
  * probelsiz kiritish (`🔥❤️👍`) uchun zaxira sifatida `_smart_extract_emojis`
    ishlaydi (foydalanuvchi bekorga xato ko'rmaydi).
* Saqlangan emojilar preview'da **inline tugmalar** sifatida chiziladi
  (`build_reaction_button_rows`, maksimum 5 ta) va `db.add_post` →
  scheduler → kanal posti `reply_markup` zanjirida saqlanadi.

## 2. ✏️ TAHRIRLASH TANLOV MENYUSI

**Fayllar:** `telegram_bot/handlers/pending.py`, `telegram_bot/keyboards/inline.py`,
`telegram_bot/keyboards/callback_data.py`, `telegram_bot/handlers/__init__.py`,
`telegram_bot/locales/translations.py`, `telegram_bot/locales/en_overlay.py`

* `p_edit:<post_id>` (`pending.edit_post_content_start`) endi **darhol matn
  so'ramaydi** — topshiriqdagi tanlov oynasi chiqadi:

  ```
  [📝 Matnni o'zgartirish]   [🔘 Tugma qo'shish]
  [❤️ Reaksiyalar]           [⏰ Vaqtni surish]
              [◀️ Orqaga]
  ```
* Yangi callback'lar: `p_edtx:<post_id>` (📝 matn — matn so'rovi shu orqali),
  `p_edbk` (◀️ Orqaga). Tugma/reaksiya/vaqt tugmalari mavjud, sinovdan o'tgan
  oqimlarni ochadi (`p_btn:` / `p_react:` / `p_time:`) — yangi FSM yo'q.
* IDOR guard o'zgarishsiz: begona post uchun menyu ham, matn so'rovi ham
  yuborilmaydi (fail-closed).
* Menyu tugmalari FSM holatlarida (`EDIT_POST_*`), entry point'larda va global
  ro'yxatda qayd etilgan (`_edit_post_menu_handlers`) — eski xabarlardagi
  tugmalar ham ishlaydi.
* i18n: `pend_edit_menu_title`, `pend_edit_btn_text`, `pend_edit_btn_button`,
  `pend_edit_btn_react`, `pend_edit_btn_time`, `pend_edit_btn_back` (uz/ru/en).

## 3. ❌ BEKOR QILISH OQIMI

**Fayl:** `telegram_bot/handlers/start.py` (`cancel_handler`)

* Rejalashtirilgan postni tahrirlash kontekstida (`editing_post_id` FSM'da bor)
  [❌ Bekor qilish] bosilsa, foydalanuvchi **«Kontent yaratish» sahifasiga
  o'tib ketmaydi**:
  * FSM kontekst tozalanadi (`clear_fsm_data`) — `editing_post_id`, `edit_mode`
    va boshqa sessiya kalitlari o'chadi;
  * o'rniga 📅 **Rejalashtirilgan postlar ro'yxati** chiziladi
    (`handlers.queue.scheduled_view` — yagona kanonik ekran);
  * nosozlik bo'lsa fail-safe: eski (bo'lim boshi / asosiy menyu) oqimi ishlaydi.
* Menyudagi [◀️ Orqaga] (`p_edbk`) ham xuddi shu ro'yxatga qaytaradi va FSM'ni
  tozalaydi.
* Regressiya qo'riqoni: tahrirlash konteksti BO'LMAGAN oddiy FSM'da bekor
  qilish avvalgidek bo'lim boshiga (masalan Kontent submenyusiga) qaytadi.

## 4. 💡 AI YANGILIKLAR ISHONCHLILIGI VA SHABLON

**Fayllar:** `telegram_bot/services/ai/prompts.py`,
`telegram_bot/handlers/ai_assistant.py`, `telegram_bot/handlers/magic_post.py`

* `prompts.py` da yagona manba:

  ```python
  AI_RELIABILITY_NOTE["uz"] == ("💡 Eslatma: Ushbu post AI tomonidan tuzildi. "
                                "Rasmiy manbalardan faktlarni tekshirib olishingiz tavsiya etiladi.")
  ```

  va yordamchilar: `reliability_note(lang)` (uz/ru/en, fail-safe) hamda
  `needs_reliability_note(topic, format_key=None)`.
* Eslatma qachon qo'shiladi: AI **umumiy/axborot** mavzudan (yangilik, sport,
  futbol, voqea, biznes, ob-havo ...) post tayyorlaganda. Sotuv/mahsulot
  mavzusida (narx, chegirma — faktlar foydalanuvchining o'zidan) qo'shilmaydi.
* Qo'shilish joyi — **bot xabari tagi**: `_studio_preview_text(...)` (AI Studio
  va AI Post wizard) hamda `_magic_result_text(...)` (Magic Post). Kanalga
  chiqadigan POST MATNI o'zgarmaydi — eslatma faqat ko'rinish xabarida.

## 5. 📸 VISION AI — MAHSULOT EMAS, VOQEANI TO'G'RI TANISH

**Fayllar:** `telegram_bot/utils/vision_analyzer.py`,
`telegram_bot/handlers/image_post.py`, `telegram_bot/services/ai_service.py`

* Vision system prompti endi majburiy `image_type` maydonini so'raydi:
  `product` (kiyim/tovar) yoki `event` (mashhur shaxslar, futbol/sport,
  yangilik, tabiat, hayvonlar, koncert ...). Voqea uchun rang/material
  **uydirilmasligi** alohida qoida sifatida yozilgan.
* `detect_image_type()` — model maydoni bo'lmasa ham kalit so'zlar bo'yicha
  aniqlaydi; «sport poyabzali» kabi holatlar noto'g'ri «voqea» deb
  belgilanmaydi (avval mahsulot belgilari tekshiriladi).
* `normalize_analysis()` natijasiga `image_type` va avtomatik `category_label`
  qo'shiladi; voqea uchun `visual_features` neytrallashtiriladi
  (`noma'lum` — rang/material so'ralmaydi).
* Avtomatik toifa yorliqlari (topshiriq matni bilan aynan):
  `Mahsulot posti` / `Voqea / Qiziqarli kontent posti` (uz/ru/en ko'rinishlari
  `IMAGE_CATEGORY_LABELS` da).
* Bot xabari: voqea rasmi uchun `image_event_summary` — «🎉 Voqea / Qiziqarli
  kontent posti» sarlavhasi + toifa + qisqa xulosa; **«Mahsulot: Rang/Material»
  kartochkasi umuman chiqmaydi**. Mahsulot rasmi uchun eski kartochka saqlanadi.
* Generation prompti (`_image_analysis_text`) voqea uchun «mahsulot sotilmaydi —
  narx, material, o'lcham yozmang» ko'rsatmasini beradi (AI sotuv postini
  to'qimaydi).
* Uslub savoli ham toifaga moslashadi: voqea rasmi uchun «Qaysi uslubda **sotuv
  posti** tayyorlaymiz?» o'rniga neytral «Qaysi uslubda post tayyorlaymiz?»
  (`image_choose_style_event`) ko'rsatiladi; mahsulot rasmi uchun avvalgi matn
  saqlanadi.

---

## 6. Testlar va dalillar

```
$ bash tests/run_tests.sh
===== 3e5) 🎨 REAKSIYA EMOJILARI + ✏️ TAHRIRLASH MENYUSI + ❌ BEKOR QILISH =====
...
JAMI: o'tdi=96, xato=0
 5 TA UX/LOGIKA TUZATISHI 100% YASHIL ✔
...
BARCHA TESTLAR 100% YASHIL ✔
EXIT=0
```

* To'liq regressiya dalili: **20266 qator**, 75 suite bosqichi, `[FAIL]`
  qatorlari faqat `NATIJA: [OK]=.. [FAIL]=0` ko'rinishidagi jamlanmalarda
  uchraydi (haqiqiy yiqilish yo'q). To'liq log: `/home/user/full_run_final.log`
  (repo tashqarisida — ish maydonida saqlanadi).

* Yangi suite `tests/reactions_edit_cancel_vision_flow_test.py` runner'ga
  **3e5** bosqichi sifatida qo'shildi (run_tests.sh ichidagi batafsil izoh bilan).
* To'liq yugurish davomida **ikkita eski qo'riqchi test** tahrirlash
  menyusi bilan to'qnashdi va ikkalasi ham mahsulot tomonida tuzatildi
  (testlar zaiflashtirilmadi):
  1. `refactor_step2_test.py` — `handlers/start.py` da
     `from handlers.queue import scheduled_view` aynan 2 marta uchrashini
     talab qiladi. 📅 ro'yxatga qaytish mantig'i `handlers/navigation.py` ga
     (`render_scheduled_posts_screen` / `render_scheduled_posts_edit`) chiqarildi
     va o'sha yordamchilar kanonik `scheduled_view` dan foydalanadi — shartnoma
     saqlandi, dublikat ekran paydo bo'lmadi.
  2. `postassist_polish_test.py` — inline yorliqlar ≤18 belgi standarti.
     Topshiriqda **aynan** talab qilingan `📝 Matnni o'zgartirish` (21 belgi)
     speskdagi imtiyozli ro'yxatga qo'shildi. Qolgan menyu yorliqlari
     standartga sig'adi: `🔘 Tugma qo'shish` (16), `⏰ Vaqtni surish` (15),
     `❤️ Reaksiyalar` (14), `◀️ Orqaga` (9).
* Qo'shimcha ravishda tegilgan sohalar regressiyasi alohida yugurtirildi:
  `unit_test` (2628 OK), `final_acceptance_suite_test` (587 OK),
  `production_hardening_and_concurrency_test` (126 PASS),
  `image_post_fallback_test` (180 OK), `image_to_post_flow_test` (30 OK),
  `ai_engine_v2_test` (146 OK), `channels_and_queue_v2_test` (281 OK),
  `refactor_step4_test` (279 OK), `i18n_full_parity_test` (347 OK),
  `ui_ux_and_navigation_standards_test` (187 OK), `fsm_navigation_safety_test`.
