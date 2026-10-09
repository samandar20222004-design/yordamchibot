# PostAssist AI Refactor — 2-BOSQICH: AI PROMPT VA MAGIC POST SIFATI

**Holat:** ✅ Bajarildi · `PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh` → **BARCHA TESTLAR 100% YASHIL (0 FAIL)**

## 1. Muammo (skrinshotlar asosida)

| Muammo | Sabab | Yechim |
|---|---|---|
| «sport haqida bo'lsin futbol bo'yicha» → 1 qatorli robotik matn («Sportlar boshqalariga qoling: futbol bo'yicha») | Tizim promptida majburiy tuzilma yo'q edi; AI qisqa mavzuni shunchaki qaytarib yozardi; javob sifati tekshirilmasdi | Majburiy 4 qismli SMM skelet + rolda «qisqa mavzuni CHUQUR ochish» talabi + sifat validatori + yupqa javobda kuchaytirilgan qayta so'rov |
| «Magic Post» ochilganda 15 qatorli tushuntirish | `mp_intro`da 5 uslub tavsifi takrorlanardi (uslublar keyingi ekranda baribir chiqadi) | Ixcham 3 qatorli SaaS taklifi |
| Uslublar real Telegram postlariga o'xshamasdi | Uslub speclari yuzaki, til sifati talabi yo'q | Har uslub uchun aniq formula + o'zbek tili sifati / xom tarjima taqiqi |

## 2. System promptlar (`telegram_bot/utils/ai_agent.py`)

Yakuniy prompt tartibi: **ROL → MAJBURIY TUZILMA → USLUB → FORMAT** (+ `with_language` qat'iy til bloki).

* **`_MAGIC_POST_ROLE`** — 10 yillik SMM kopirayter; bitta so'z («futbol») ham to'liq postga aylanadi, foydalanuvchi so'zlari takrorlanmaydi, faktlar o'ylab topilmaydi (`[placeholder]`).
* **`_MAGIC_POST_STRUCTURE`** (yangi, uz/ru/en) — har postda majburiy:
  1. **Hook** — `<b>qalin sarlavha</b>` + 1-2 emoji;
  2. **Asosiy mazmun** — kamida 2-4 punkt/abzats, har biri haqiqiy qiymat;
  3. **Call-To-Action** — savol / muhokama / ulashish / obuna;
  4. **3-5 hashtag** — oxirgi alohida qatorda.
  Qat'iy taqiqlar: 1-2 qatorli quruq jumla, matnni takrorlash, ma'nosiz umumiy gaplar, so'zma-so'z tarjima, 5 qatordan qisqa post.
* **`_MAGIC_POST_STYLE_SPEC`** — real farqlanuvchi uslublar:
  * 🔥 Sotuv — AIDA/PAS, foyda (xususiyat emas), **aniq taklif**, shoshilinchlik, bitta CTA;
  * 📰 Informativ — foydali faktlar, 3-5 punkt, **ekspert xulosasi**;
  * 💎 Premium — nafis, lakonik, estetik, ishonchli; aksiya toni taqiqlangan;
  * 😊 Oddiy/Blogerona — samimiy, **hayotiy misollar**, majburiy savol;
  * 📢 Reklama — skroll to'xtatuvchi sarlavha, offer, havola joyi, kuchli CTA.
* **`_MAGIC_POST_FORMAT_RULES`** — «300 belgidan qisqa post — XATO», **tabiiy o'zbek tili** (ruscha/inglizcha konstruksiyalarni so'zma-so'z ko'chirish taqiqi, «sportlar boshqalariga qoling» kabi g'aliz jumlalar mumkin emas), Telegram HTML, JSON kontrakti.

### Sifat nazorati (yangi)
* `magic_post_quality_report(text)` → `{ok, hook, body, lines, cta, hashtags, body_chars, content_lines, hashtag_count, issues}`.
* `is_magic_post_too_thin(text)` — 1-2 qatorli / hook va CTA'siz robotik matnni aniqlaydi (hashtag yetishmasligi hisobga olinmaydi — `ensure_magic_hashtags` to'ldiradi).
* `generate_magic_post` — yupqa javobda `_MAGIC_POST_RETRY_HINT` (uz/ru/en) bilan **bir marta** qayta so'raydi, yaxshirog'ini qaytaradi; natijaga `quality` va `retried` maydonlari qo'shildi. Retry xatosi yutiladi — oqim hech qachon bo'sh qolmaydi. Yaxshi javobda qo'shimcha so'rov yo'q.

## 3. UI ixchamlashtirish

* **`mp_intro`** (uz):
  > ✨ **Magic Post** — G'oyadan tayyor postgacha!
  >
  > Post mavzusini yozing, mahsulot tavsifini qoldiring yoki shunchaki ovoz/rasm yuboring:
* **Natija klaviaturasi** (`_magic_action_keyboard`):
  ```
  [📢 Kanalga yuborish]      [📅 Rejalashtirish]
  [✏️ Qayta yozish / Uslub]  [📊 Baholash]
              [◀️ Orqaga]
  ```
  `mp_restyle` callback'i saqlandi (eski chat tarixidagi tugmalar ishlaydi); yangi `mp_back` → Kontent yaratish submenyusi (navigatsiya stacki, END).
* **Ovoz/rasm Magic Post ichida** — intro va'dasiga mos: `MAGIC_INPUT`da ovoz → `voice_message_received` (🎙 Ovoz → Post), rasm → `image_photo_received` (📸 Rasm → Post). Boshqa media uchun avvalgidek ixcham hint.
* Yangi i18n kalitlar: `mp_btn_rewrite`, `mp_btn_back` (UZ/RU/EN, paritet `in_sync: True`).

## 4. Testlar

* **Yangi:** `tests/ai_prompt_quality_test.py` — 155 tekshiruv (3n bosqichi `tests/run_tests.sh`da):
  1. 5 uslub × 3 til promptlarida majburiy tuzilma va taqiqlar, uslublar farqli;
  2. Sifat validatori: yaxshi post o'tadi, robotik 1 qator rad etiladi (uz/ru/en);
  3. `generate_magic_post` retry mantiqi (yupqa → kuchaytirilgan so'rov; yaxshi → 1 chaqiruv; ikkalasi yupqa → oqim uzilmaydi; retry istisnosi yutiladi);
  4. Ixcham intro + [2,2,1] klaviatura + i18n paritet + callback ≤ 64 bayt;
  5. Regressiya: FSM 430-433, `mp_back`, ovoz/rasm routing.
* **Yangilangan:** `tests/magic_post_flow_test.py`, `tests/post_score_flow_test.py` — yangi layout/intro kutilmalari.
* Barcha mavjud FSM oqimlari, UZ/RU/EN va testlar yashil.
