# 🧩 KONTENT YARATISH submenu + ACTION-FIRST — hisobot (PostAssist V2)

**Sana:** 2026-09-14
**Sessiya branch:** `arena/01a09dbf-yordamchibot`
**Repozitoriy:** `samandar20222004-design/yordamchibot`
**Testlar:** `PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh` → **100% YASHIL**

## Xulosa

Topshiriqdagi 3 mikro qadam to'liq bajarildi. Mavjud **6719** ta yashil
tekshovdan birortasi ham o'chirilmadi/yumshatilmadi — aksincha, yangi
`tests/content_creation_menu_test.py` bilan **268** ta yangi tekshov
qo'shildi va yakuniy hisob **6993 `[OK]` / 0 `[FAIL]`** (baseline 6719;
6719→6725 ko'tarilgan qismi AI provayder zanjiriga bog'liq o'zgaruvchan
tekshovlar, bu PR bilan aloqasi yo'q). Hech qanday killer featura
(Magic Post / Voice→Post / Image→Post Vision / Post Score / AI Studio /
to'lov / moderatsiya / admin) xulqiy o'zgarishga uchramadi: submenu faqat
**yangi kirish yo'llarini** qo'shadi.

| Qadam | Holat | Qayerda |
|---|---|---|
| 1. `✨ KONTENT YARATISH` ichki menyusi: 5 tugma + ◀️ Orqaga, UZ/RU/EN parity | ✅ | `keyboards/default.py`, `keyboards/reply.py`, `translations/content_menu.py` |
| 2. Routing: har bir tugma o'z oqimini ochadi, ◀️ Orqaga → 6 tugmali menyu | ✅ | `handlers/__init__.py` (`content_creation_handlers`), `handlers/voice_post.py`, `handlers/ai_assistant.py`, `handlers/content_creation.py` |
| 3. ACTION-FIRST: ovoz → STT, rasm → Vision, xom matn → «✨ Magic Post» taklifi | ✅ (matn taklifi yangi) | `handlers/__init__.py` (`unknown_message_fallback`), `handlers/content_creation.py` |
| 4. Yangi test fayli + to'liq suite yashil | ✅ | `tests/content_creation_menu_test.py`, `tests/run_tests.sh` (3e bosqichi) |

## 1-qadam — submenu klaviaturasi

`[✨ Kontent yaratish]` bosilganda pastki (reply) klaviaturada aynan quyidagi
5 tugma + ◀️ Orqaga chiziladi (qatorlar speksdagi tartibda):

```
[✨ Magic Post]   [📝 Matn → Post]
[📸 Rasm → Post]  [🎙 Ovoz → Post]
        [🤖 AI Yordamchi]
            [◀️ Orqaga]
```

* **Yorliqlar yagona manbada:** `telegram_bot/translations/content_menu.py`
  (`CONTENT_MENU_I18N` → `cm_btn_*`) — `keyboards/default.py` shu paketdan
  oladi, xuddi `MAGIC_POST_I18N` va `POST_SCORE_I18N` kabi; shu sababli RU/EN
  klaviaturalari ham avtomatik sinxron. Asosiy `locales/translations.py` +
  `en_overlay.py` **o'zgartirilmadi** (ular qat'iy i18n audit-testlari bilan
  himoyalangan — regressiya xavfi yo'q).
* **Pariteti hisobot bilan qo'riqlanadi:** `content_menu_parity_report()`
  (UZ↔RU↔EN kalitlar, format argumentlari, bo'sh matnlar) — `magic_post` va
  `voice_post` bilan bir xil struktura.
* **Dublikat yo'q:** «✨ Magic Post» `BTN_MAGIC_POST_*` bilan, «📸 Rasm → Post»
  `BTN_IMAGE_POST_*` bilan **aynan bir xil** yorliqni `cm_btn_magic` /
  `cm_btn_image` orqali qayta ishlatadi (bir yorliq — bitta amal, registry'da
  ham bitta oila).
* **`keyboards/reply.py`** — yangi fayl: pastki klaviaturalar uchun hujjatlashtirilgan
  fassad (`default.py` — yagona mantiq manbasi, siklik import yo'q).
* Asosiy menyudagi **qat'iy 6 tugma standarti** (`get_main_keyboard`)
  o'zgarmadi — submenu unga aralashmaydi (`tests/ux_v2_main_menu_test.py` ham
  yashil).

## 2-qadam — routing (har tugma o'z oqimiga)

| Tugma | Handler | Natija |
|---|---|---|
| ✨ Magic Post | `magic_post.magic_post_entry` | `MAGIC_INPUT` → matn → 5 uslub |
| 📝 Matn → Post | `new_post.start_new_post` | `CHOOSE_CHANNEL` (oddiy matnli post oqimi) |
| 📸 Rasm → Post | `image_post.image_post_entry` | `IMAGE_POST_INPUT` → Gemini Vision |
| 🎙 Ovoz → Post | `voice_post.voice_post_entry` (**yangi**) | `VOICE_AWAIT` (**yangi holat**) → STT |
| 🤖 AI Yordamchi | `ai_assistant.ai_studio_hub_entry` (**yangi**) | `AI_MENU_STATE` — AI Studio bo'limi |
| ◀️ Orqaga | `content_creation.content_creation_back` (**yangi**) | asosiy 6 tugmali menyu, `END` |

* **Yangi yo'riqnomalar speks matni bilan:**
  * 🎙 — `vp_intro`: «Iltimos, g'oyangizni ovozli xabar (1 daqiqa ichida)
    qilib yuboring…» (uz/ru/en);
  * 📸 — `image_post_intro` («Rasm yuboring…») — mavjud, sinovdan o'tgan
    Vision yo'riqnomasi saqlab qolindi (submenu matnida «iltimos, mahsulot
    rasmini yuboring» talabi ham beriladi).
* **`ai_studio_menu_entry` endi submenu'ni chizadi** va `ConversationHandler.END`
  qaytaradi — ataylab: submenu FSM holatini **ochmaydi**, shunda action-first
  kirishlar (ovoz/rasm/matn) dialog to'sig'iga urilmaydi. AI Studio'ning
  klassik inline hub'i `ai_studio_hub_entry` ko'rinishida **to'liq saqlanib**,
  🤖 AI Yordamchi tugmasidan ochiladi (meros `✨ AI Studio` yorlig'i ham
    submenu'ga tushadi — UX V2 dagi «kontent markazi» g'oyasi).
* Routing `exact()` + `MENU_TEXTS` registry orqali qo'shildi: yangi oilalar
  `content_text_post`, `content_voice_post`, `content_ai`, `content_back` —
  har biri uchala tilda to'liq (reply tugma qaysi tilda chizilganiga qaramay
  ishlaydi). Yangi guruh `all_menu_jumps`ga qo'shilgani uchun submenu
  tugmalari **dialog ichida ham** avvalgidek ishlaydi.

## 3-qadam — ACTION-FIRST (menyu tashqarisida)

* **Ovozli xabar** → `VoiceEntryHandler` (mavjud) STT oqimini darhol boshlaydi.
* **Rasm** → `ImageEntryHandler` (mavjud) Image → Post / Vision oqimini boshlaydi.
* **Xom matn** → yangi: `unknown_message_fallback` ichida **gatlantirilgan**
  tarmoq — matn postga yetarli bo'lsa (`≥ 40` belgi **va** `≥ 5` so'z, `/buyruq`
  emas) «✨ Magic Post» taklifi + inline tugmalar ([✨ Magic Post bilan
  tayyorlash] / [🔙 Asosiy menyu]) yuboriladi. Qisqa yoki tushunarsiz xabarlar
  (**`???`, `hello?`, `/nomalum`**) uchun eski xushmuomala javob + asosiy menyu
  o'zgarishsiz qoladi.
* Taklif bosilganda matn **yo'qolmaydi**: `cc_magic` `magic_raw_text`ni
  tiklaydi va darhol **uslub tanlash** ekranini (`MAGIC_STYLE_SELECT`) ochadi —
  kredit/limit preflichti `magic_style_callback` ichida avvalgidek bajariladi.
  Matn eskirgan bo'lsa (20 daq. TTL) Magic oqimi bo'sh holida ochiladi
  (`MAGIC_INPUT`) — hech qachon «o'lik tugma» emas.
* **Himoya:** `cc_` tugmalari `ContentOfferEntryHandler` orqali main_conv
  **entry point**i sifatida ro'yxatdan o'tadi va PTB `allow_reentry=True`
  bo'lganda ham **faol dialog ichida mos kelmaydi** (`_is_inside_dialog`,
  `image_post`/`voice_post` bilan bir xil usul) — to'lov, kanal ulash,
  new-post va moderatsiya suhbatlari buzilmaydi. Global stale-handler'lar
  (`^mp_`, `^vp_`, `^ps_`, `^image_`, `^photo_`) bilan to'qnashuv yo'q:
  «sessiya eskirgan» toast'i chiqmaydi.
* Foydalanuvchi ko'radigan barcha yangi matnlar `translations/content_menu.py`
  da (`cm_offer_text`, `cm_offer_magic`, `cm_offer_menu`) — `handlers/__init__.py`
  ichida hardcode qilingan toast/matn yo'q (i18n full-parity auditi talabi).

## 4-qadam — testlar

`tests/content_creation_menu_test.py` (**268 tekshov**, 6 blok, ruff/flake8
lint-gate toza):

1. **TEST 1** — submenu klaviaturasi: aynan 5 tugma + ◀️ Orqaga, qatorlar
   speksdagi tartibda (uz/ru/en), takror yo'q, asosiy 6 tugma menyuga
   aralashmaydi; admin 7 tugma.
2. **TEST 2** — UZ/RU/EN **parity**: `content_menu_parity_report().in_sync`,
   har bir `cm_btn_*` uchala tilda to'liq va farqli (brend `✨ Magic Post`
   mustasno), Magic/Image yorliqlari killer featuralar konstantalari bilan
   aynan bir xil, `MENU_TEXTS` oilalari to'liq, `voice_post` va `magic_post`
   paritet hisobotlari ham `in_sync`.
3. **TEST 3** — **routing** (haqiqiy `register_all_handlers` + PTB filtrlari):
   har bir submenu tugmasi 3 tilda ham o'z handleriga tushadi, fallback'ga
   tushmaydi; `✨ Kontent yaratish` / `✨ AI Studio` → `ai_studio_menu_entry`;
   dialog ICHIDA (MAGIC_INPUT, IMAGE_POST_INPUT, CHOOSE_CHANNEL, VOICE_AWAIT,
   AI_MENU_STATE, MAGIC_STYLE_SELECT) ham menu-jump sifatida ishlaydi.
4. **TEST 4** — **oqimlar** (handlerlar haqiqiy chaqiriladi, xatosiz): submenu
   ochilishi, kanal tanlash, Vision yo'riqnomasi, `vp_intro` aniq matni
   («1 daqiqa ichida»), `VOICE_AWAIT`, AI bo'limi + 5 vosita, ◀️ Orqaga → asosiy
   6 tugma, Magic Post `MAGIC_INPUT`.
5. **TEST 5** — **ACTION-FIRST**: ovoz/rasm entry point'lari, dialog ichida
   himoyalanishi, `cc_` entry point'i, gate chegaralari, uzun matnda taklif +
   `cc_magic` → `MAGIC_STYLE_SELECT` (matn saqlanadi, 5 uslub tugmasi),
   `cc_menu` → asosiy menyu, matnsiz → `MAGIC_INPUT`, TTL, qisqa matnda eski
   fallback matni + asosiy menyu (uz/ru).
6. **TEST 6** — **regressiya qo'riqonlari**: fallback eng oxirgi handler bo'lib
   qoldi, `receipt_admin_callback → expired_session_callback` tartibi buzilmagan,
   FSM holatlari noyob (`VOICE_AWAIT = 439` — band bo'shliq), eski holat
   qiymatlari o'zgarmagan, `cc_` stale-pattern'larga tushmaydi, asosiy menyu 6
   tugma, `allow_reentry`/timeout saqlangan, `handlers/__init__.py` da hardcode
   matn yo'q, `vp_intro` 3 tilda.

Runner bosqichi: `tests/run_tests.sh` → **3e** (`#   3e) 🧩 KONTENT YARATISH
submenu + ACTION-FIRST`). `telegram_bot/tests/syntax_test.py` import ro'yxatiga
3 ta yangi modul qo'shildi.

## O'zgartirilgan fayllar

| Fayl | O'zgarish |
|---|---|
| `telegram_bot/translations/content_menu.py` | **yangi** — `CONTENT_MENU_I18N` (uz/ru/en), `content_menu_t`, `content_menu_parity_report`, `CONTENT_MENU_KEYS` |
| `telegram_bot/translations/__init__.py` | yangi moddni qayta eksport qiladi |
| `telegram_bot/translations/voice_post.py` | `vp_intro` kaliti (uz/ru/en) + docstring |
| `telegram_bot/keyboards/default.py` | `cm_btn_*` yorliklari, `BTN_CONTENT_*` konstantalari, 4 ta MENU_TEXTS oilasi, `content_creation_rows/labels`, `get_content_creation_keyboard` |
| `telegram_bot/keyboards/reply.py` | **yangi** — reply-klaviatura fassadi |
| `telegram_bot/handlers/content_creation.py` | **yangi** — ◀️ Orqaga, action-first taklif, `cc_` entry handler + dialog himoyasi, TTL kesh |
| `telegram_bot/handlers/voice_post.py` | `VOICE_AWAIT = 439` + `voice_post_entry` |
| `telegram_bot/handlers/ai_assistant.py` | `ai_studio_menu_entry` → submenu; `ai_studio_hub_entry` → AI Studio bo'limi |
| `telegram_bot/handlers/__init__.py` | `content_creation_handlers` guruhi, `all_menu_jumps`, `VOICE_AWAIT` holati, `cc_` entry point, `unknown_message_fallback` tarmog'i, importlar |
| `tests/content_creation_menu_test.py` | **yangi** — 265 tekshov |
| `tests/run_tests.sh` | 3e bosqichi + sarlavha izohi |
| `telegram_bot/tests/syntax_test.py` | yangi modullar import ro'yxatida |
| `telegram_bot/README.md` | «🧩 Kontent yaratish — ichki menyu va ACTION-FIRST» bo'limi |

## Nega mavjud testlarga TEGLINMADI?

`tests/ux_v2_main_menu_test.py` va `telegram_bot/tests/unit_test.py`
`✨ Kontent yaratish` / `✨ AI Studio` tugmalarini `ai_studio_menu_entry` nomiga
bog'laydi. Shu nom **saqlab qolindi** (endi u submenu'ni chizadi), AI Studio
hub'i esa alohida `ai_studio_hub_entry` funksiyasiga ko'chirildi — natijada
routing audtlari o'zgarishsiz yashil, eski testlar esa yangi UX'ga moslab
qayta yozishga muhtoj bo'lmadi.
