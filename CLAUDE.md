# CLAUDE.md — PostAssist (yordamchibot)

Bu fayl har bir yangi Claude sessiyasida avtomatik o'qiladi. Loyiha egasi bilan
**o'zbek tilida** gaplash. Tuzilish va kod qoidalari — `README.md`; bot
imkoniyatlari — `telegram_bot/README.md`; deploy — `DEPLOYMENT.md`.

## Loyiha qisqacha

Telegram kanallar uchun bot (python-telegram-bot 21+, PostgreSQL/psycopg2,
APScheduler). Post yozish (qo'lda / AI), rejalashtirish, kanalga yuborish,
statistika, PRO obuna (Stars, karta, Payme). Interfeys: uz / ru / en.

## Ish qoidalari (egasining talablari)

- Avval mavjud narsani to'g'irla, keyin yangilik qo'sh. Keraksiz refaktoring qilma.
- Har o'zgarishdan keyin testlarni ishga tushir; natijani haqiqiy raqamlar bilan ayt.
- Testni o'tkazish uchun tekshiruvni o'chirma — xulq o'zgargan bo'lsa testni moslab yangila.
- Har bir yangi matn uch tilda (uz/ru/en). Tugma yorlig'i ≤18 belgi
  (`tests/postassist_polish_test.py` tekshiradi).
- `main` ga merge qilma va deploy qilma — egasi o'zi qiladi.
- Commit xabarlari o'zbekcha, aniq.

## Testlar

```bash
cd telegram_bot
ruff check ..
BOT_TOKEN=1:x PYTHONPATH=. bash tests/run_tests.sh      # oxirida yiqilganlar ro'yxati
bash ../scripts/security_check.sh                        # ruff, flake8, pip-audit, bandit
```

Haqiqiy PostgreSQL bilan testlar uchun `*_TEST_DATABASE_URL` (P0_, STEP5_, FINAL_,
RBAC_, INTEGRITY_, LOAD_, STRESS_) o'zgaruvchilarini lokal bazaga qarating.
Oxirgi natija (audit tuzatishlaridan keyin, lokal PG bilan): 18 480 `[OK]`, 0 `[XATO]`, 15 `[SKIP]` (pgserver/redis/AI_BUDGET URL yo'q). `refactor_step5_test` TOZA bazani kutadi: ishlatilgan bazada yiqiladi (baseline'da ham), yangi bazada 156/156.

## Qilingan ishlar (PR samandar20222004-design/yordamchibot#216, branch `claude/bot-kod-tuzatish-vs3iix`)

- **Tezlik:** oddiy o'qishlar autocommit — bazaga 3 emas 1 marta boradi
  (`database.py`, `_Transaction.fast_read`). 2 s dan sekin javob logga yoziladi
  (`SLOW_UPDATE_SECONDS`, foydalanuvchi matni logga tushmaydi).
- **Xatolar:** `user_settings` jadvali schema.sql'da yo'q edi va saqlash commit
  qilmasdi (tuzatildi); o'chirishga tasdiq (`qdel:<id>:ok`, `ch_del:<id>:ok`);
  «Bekor qilish»dan keyin asosiy menyu qaytadi; bitta «Post yaratish» menyusi;
  eski «Kabinet» menyusi olib tashlandi; Autopilot HTML-escape.
- **Tozalash:** eskirgan AI shimlari, o'lik modullar/funksiyalar, `docs/archive`,
  `tools/` o'chirildi; izohlardan «PHASE/BOSQICH/SPRINT» belgilari olindi.
- **🧹 Tezkor post tozalagich (yangi):** `/cleaner` → imzo bir marta sozlanadi
  (havola yoki havolali matn; 10 qator / 300 so'z / 2000 belgi) → «🧹 Boshlash»
  rejimi: har bir post oxiridagi begona havola/reklama qatorlari olinadi, matn
  o'zgarmaydi, imzo qo'shiladi, kanalga darhol yuboriladi.
  Fayllar: `handlers/post_cleaner_flow.py`, `services/post_cleaner.py`
  (`quick_clean`, `strip_tail_junk`), `scheduler.deliver_due_posts_now`,
  ustun `users.post_signature_html`. Test: `tests/post_cleaner_quick_test.py`.
- `main` (PR #213 — Sozlamalar 3-qatori: Do'stlarni taklif + Yordam) branchga merge qilingan.
- **Umumiy kunlik AI chegarasi:** `AI_GLOBAL_DAILY_USD` (USD, barcha foydalanuvchi va
  instance'lar, UTC kun; 0 = o'chiq, sukut — DB'ga tegilmaydi). Tekshiruv va bron
  PostgreSQL'da ATOMIK (`repositories/ai_budget_repository.py`, jadvallar
  `ai_budget_days` / `ai_budget_reservations`, `pg_advisory_xact_lock`). `BudgetGuard.acquire`
  foydalanuvchi limitlaridan keyin bron qiladi; `finalize` yakunlaydi: muvaffaqiyat →
  `estimated_cost` va ALOHIDA `assumed_usd`; aniq xato (429/5xx/tarmoq) → bron qaytadi;
  timeout/bekor/noma'lum → bron `unknown_usd` da hisobda QOLADI; TTL
  (`AI_GLOBAL_TICKET_TTL_SECONDS`) bronni o'chirmaydi, `expired` → `unknown_usd`,
  kechikkan `settle/release` to'g'rilaydi. Chegara yoqilgan va DB xato bersa —
  yangi pullik so'rov rad (`global_unavailable`, fail-closed). Kesh va AI'siz
  funksiyalar bloklanmaydi. Hodisalar `ai_usage_events` ga yoziladi
  (`services/ai/usage_store.py`, `AI_USAGE_PERSIST`). Testlar:
  `tests/ai_global_budget_test.py`, `tests/ai_budget_reservation_test.py`,
  `tests/ai_usage_persistence_test.py` (jonli qism: `AI_BUDGET_TEST_DATABASE_URL` —
  FAQAT sinov bazasi, jadvallar tozalanadi).

- **Tarif/kredit qoidalari (tuzatilgan):** enterprise (muddatsiz) foydalanuvchi to'lov/obuna/promo orqali PRO ga
  TUSHMAYDI (Stars/karta, `SubscriptionService.activate/extend`, Payme grant/revoke, promo; qoida
  `sync_stars_subscription` dan olingan); kecha yaratilgan AI bron bugungi kunlik hisoblagichni kamaytirmaydi
  (`refund_ai_request`); kunlik faollik bonusi parallel chaqiruvda ikki marta berilmaydi (users qatori `FOR UPDATE`).
  Testlar: `enterprise_plan_preservation_test`, `ai_refund_period_test`, `credits_bonus_concurrency_test` (real PG, SKIP agar URL yo'q).

- **Ovozli/tabiiy til rejalash (bot):** post vaqti bosqichida (`handlers/schedule_smart.py`) matn («har dam olish kuni 12:00», «ikki kunda bir») AI'siz, ovoz — kvota bilan (free butun umr 1, PRO 24 soatda 20, admin cheksiz; `services/voice_schedule_quota.py`, jadval `voice_schedule_usage`, env `FREE_VOICE_SCHEDULE_TOTAL`/`PRO_VOICE_SCHEDULE_DAILY`). Bron STT'dan oldin, xatoda qaytadi, DB xatosida rad. Takrorlanish turlari: interval/weekdays (`services/recurrence.py`, `services/schedule_nlp.py`). Testlar: `schedule_smart_test`, `voice_schedule_quota_test`. Batafsil — `docs/SMART_SCHEDULE.md`.

- **Tariflar (FREE/PRO/ULTRA, 4 muddat 1/3/6/12 oy):** yagona manba `config.TARIFF_CATALOG` + `TIER_LIMITS`; narx/limit/qoidalar — `docs/PLANS.md`. `services/plan_sql.py` (tarif berishning yagona SQL qoidasi), `users.pro_legacy_until` (eski to'langan PRO limitlari tugaguncha saqlanadi; bir martalik migratsiya schema.sql'da), tarif kalitlari `1m 3m 6m 1y` (PRO) va `u1m..u1y` (ULTRA). Test: `tariff_tiers_test`.

## 📱 Mini App (yangi, `MINIAPP_ENABLED=0` — sukut bo'yicha O'CHIQ)

Vite + React + TS frontend `miniapp/`, backend qatlami `telegram_bot/miniapp_api/` (o'qish: `/api/v1/health|me|channels|scheduled-posts|posts/{id}`;
yozish: `POST/PATCH/DELETE /posts`, `PATCH /me/settings`, `POST /ai/generate`; `/app/*` statik; yuborishni bot scheduler'i bajaradi). Batafsil, xavfsizlik qarorlari va
sozlamalar — `miniapp/README.md`. Testlar: `tests/miniapp_*_test.py` (+ `cd miniapp && npm test`).

- **Bot -> Mini App qoralama (PostBot uslubi):** Mini App yoqilgan bo'lsa botdagi post tasdiqlash kartasida «📱 Mini App'da» (web_app) tugmasi; post `miniapp_drafts` ga yoziladi (bitta joriy qoralama, 48 soat). Mini App qoralama bilan ochilsa to'g'ridan-to'g'ri tahrirlagichga tushadi (format paneli, Telegram ko'rinishi, tugma, tez vaqt). Kod: `miniapp_api/drafts.py`, `handlers/new_post.py:_save_miniapp_draft`; test: `tests/miniapp_draft_test.py`, `miniapp/src/draft.test.tsx`.

- **Yuklash ekrani (Mini App):** robot + Telegram belgisi animatsiyasi (`components/BrandMark.tsx` SVG, `components/ui.tsx:Splash`, uslub `styles/base.css`; manba `scripts/brand/`); `index.html` ichida xuddi shu statik splash (JS yuklanguncha), birinchi `/me` kelguncha React `Splash` ko'rsatadi. `prefers-reduced-motion` hurmat qilinadi.
- **Sozlamalar (Men) sahifasi:** profil muqovasi (Telegram `photo_url`, faqat https; yuklanmasa bosh harf), bo'limlar: Tarif va limitlar / Til / Kanallar / Ilova.
- **Mini App media ko'rinishi:** qoralamadagi rasm, video, GIF, rasm-hujjat va albomning birinchi fayli `/draft/media` orqali ko'rsatiladi (tur baytlardan aniqlanadi; CSP `media-src blob:`; hajm 16 MB gacha).

- **Bot <-> Mini App bog'lanishi:** Mini App yoqilgan bo'lsa bot «📱 Mini App» web_app tugmasini ko'rsatadi: Sozlamalar (tab=me), Rejalashtirilgan ro'yxat (tab=schedule), Tahlil (tab=me), post tasdiqlash kartasi (qoralama), `/app` va `/miniapp` buyrug'i; Mini App `?tab=home|post|schedule|me` ni o'qiydi (boshqa qiymat e'tiborsiz). O'chiq bo'lsa bot ekranlari o'zgarmaydi. Kod: `miniapp_api/menu.py` (`miniapp_tab_url`, `miniapp_button`, `with_miniapp_row`); test: `tests/miniapp_bot_links_test.py`. Mini App -> bot: «Botni ochish» (oddiy havola; `?start=` yo'q — xavfsizlik testi). To'lov, referal, autopilot, kontent-reja — faqat botda (ataylab); jamoa va rol Mini App’da ham bor (Men → Jamoa va rol).

- **Kuniga ikki vaqt (`twice`):** bitta post ertalab va kechqurun chiqadi: `recurrence_type='twice'`, `recurrence_time` = erta vaqt, `recurrence_day` = kech vaqt (kun boshidan daqiqa) — sxema o'zgarmagan (`services/recurrence.py`: `twice_times`, `next_twice_occurrence`). Rejalash matni: «har kuni ertalab 9 va kechqurun 18:30 da» (`schedule_nlp.extract_two_times`); Mini App: `time2` (HH:MM), takrorlash tanlovida «kuniga 2 marta».
- **Mini App post tahrirlash:** `PATCH /posts/{id}` — matn, vaqt, tugma, takrorlanuvchida kun vaqtlari; `GET/POST/DELETE /posts/{id}/media` (ro'yxat rasmi, almashtirish, olib tashlash; rasm klientda siqiladi, ro'yxatda lazy + 3 parallel + server LRU kesh). Testlar: `tests/miniapp_post_edit_test.py`, `miniapp/src/edit.test.tsx`.

- **Yuklash tezligi:** `index.html` da `#boot` yuklash ekrani (birinchi kadrdan ilova tayyor bo'lguncha BITTA animatsiya; `src/boot.ts:hideBoot`), Telegram SDK `defer`; build `scripts/compress-dist.mjs` bilan `.br`/`.gz` yaratadi (aiohttp o'zi beradi: JS ~350 KB -> ~90 KB).
- **Profil (Men):** qatorlar Tarif / Til / Kanallarim alohida ekranlarda (`PlansScreen`: davr 1/3/6/12 oy, narx, Stars, tejam, limitlar; `LanguageScreen`; `ChannelsScreen`); `/me` `tiers.{free,pro,ultra}.periods`.

- **Mini App dizayni («vau» qatlami):** `miniapp/src/styles/wow.css` (aurora fon, suzuvchi pastki panel, kirish animatsiyalari, `CountUp`, `haptic`). Mini App -> bot deep-link ruxsat ro'yxati: `go_plans|go_settings|go_help|go_channels|go_invite` (`handlers/start.py:MINIAPP_GO_TARGETS` va `miniapp/src/telegram.ts:BOT_SECTIONS` AYNAN bir xil bo'lishi `tests/miniapp_navigation_test.py` da tekshiriladi). Bosh sahifada «Botdagi imkoniyatlar».

- **Imzo/tozalagich tugmalari botdan OLIB TASHLANDI** (egasi talabi): Sozlamalar hub'i endi 6 tugma (2+2+2, «Jamoa va rol» qo'shilgan), ☰ menyuda va ro'yxatda `/cleaner` yo'q. Ichki mantiq (`handlers/post_cleaner_flow.py`, `services/post_cleaner.py`) kodda qolgan — foydalanuvchi interfeysisiz; QAYTARMANG.
- **Mini App -> bot:** `openBot` chatni ochgach Mini App'ni yopadi (`telegram.ts`), shunda foydalanuvchi botda qoladi.
- **Bot /start animatsiyasi OLIB TASHLANDI** (egasi: 1 soniya ko'rinib yo'qolardi va /start'ni sekinlashtirardi). Qaytarmang.

- **💰 Reklama birjasi (yangi):** `/market` + kanal panelidagi «💰 Reklama birjasi» tugmasi + birinchi kanal ulanganda taklif. Kanal egasi kanalini qo'yadi (ochiq kanal, bot va egasi admin — jonli tekshiruv), reklama beruvchi katalogdan bot hisoblagan ko'rsatkichlar (obunachi, o'rtacha ko'rish, ER, o'sish; noma'lum bo'lsa «ma'lumot yetarli emas») bilan ko'radi, so'rov yozadi, yozishma bot orqali o'tadi (kontakt faqat o'zi ruxsat bersa ulashiladi). Pul botdan O'TMAYDI. Himoya: kuniga 5 so'rov, blok, 3 shikoyat -> avto blok, admin `/market_ban|unban`. Kod: `handlers/ad_market.py`, `repositories/ad_market_repository.py`, `services/ad_market.py`, `translations/ad_market.py`; hujjat `docs/AD_MARKET.md`; test `tests/ad_market_test.py`. **Mini App'da ham:** «Birja» tabi (5 tab), API `miniapp_api/market.py` (`/market/*`), test `tests/miniapp_market_test.py` + `miniapp/src/market.test.tsx`. Chat ro'yxatidagi «Ochish» tugmasi — BotFather'da Main Mini App (kod sozlay olmaydi; `miniapp/README.md`). Kanal paneliga qator qo'shilgani uchun 6 ta panel testi moslandi. **Himoya (firibgarlik):** `services/market_safety.py` (karta/hamyon/havola to'siladi, oldindan to'lov va shoshiltirish belgilanadi), spam/limitlar, 🚩 Firibgar -> 3 shikoyat = global ban, `/market_userban|userunban`; test `tests/market_safety_test.py`; batafsil `docs/AD_MARKET.md`. **Mini App'da suhbat:** o'qilmagan nishoni, `?tab=market&thread=ID`, 8 s avto-yangilash. **Ko'rinish sozlamalari:** Men -> Ko'rinish (`miniapp/src/appearance.ts`, localStorage + Telegram CloudStorage).

- **👑 Super admin rejimi (Mini App) + botda «Mini App'da davom etish»:** `/me.is_admin` (rbac `ADMIN_ROLES`) bo'lsa Men -> «Super admin rejimi»: alohida admin paneli (Umumiy · Reklama · Obuna · Birja · Oddiy), `?tab=admin`. API `miniapp_api/admin.py` (`/admin/*`, har biri 403 `admin_only`; birja bloklash/ban `manage_users` huquqi bilan; audit jurnali). Frontend `miniapp/src/pages/admin/`. Botda Mini App qatori: post yaratish boshi (inline + reply), AI Studio, kanallar, shablonlar, admin panel (`menu.py:with_miniapp_row`, `miniapp_reply_button`). Bot va Mini App farqi — `docs/MINIAPP_PARITY.md`. Testlar: `tests/miniapp_admin_test.py`, `miniapp_bot_links_test.py`, `miniapp/src/admin.test.tsx`.

- **📞 Telefon tasdig'i (har davlat) va davlat statistikasi:** /start'da telefon SO'RALMAYDI. Faqat (1) tarif sotib olishda (so'm ham, Stars ham), (2) birjada e'lon qo'yishda, (3) birja katalogida «o'z mamlakatim» filtrini yoqishda so'raladi: o'z kontakti (`contact.user_id == o'zi`) -> faqat davlat ISO-2 kodi `users.phone_country` (+ UZ bo'lsa `uz_verified`), raqam SAQLANMAYDI. Kod: `services/country.py`, `handlers/phone_verify.py` (guruh -5, faqat so'ralgan kontaktni ushlaydi). Admin statistikasi (bot + Mini App) davlatlar kesimini ko'rsatadi. **Birja:** e'londa `country` va `price_currency` (UZ -> UZS, boshqa -> USD); katalog standarti — o'z mamlakati, «🌍 Hammasi» — global (Mini App `?country=all|mine|auto`); telefonsiz e'lon qo'yib bo'lmaydi (`phone_required`).
- **🕒 Vaqt mintaqasi (har davlat o'z vaqtida):** zona = `users.timezone` (qo'lda, `/timezone`) -> telefon mamlakati zonasi -> `Asia/Tashkent`. Kod `tashkent_tz` o'rniga `utz()` (`services/user_timezone.py`, ContextVar; `main.py dagi `TimezoneUpdateProcessor` (handlers/timezone_flow.py) har yangilanishda o'rnatadi); fon vazifa egasining zonasida (`use_tz`); soat/kun siljishi `shift_local` (DST); matn/AI promptlarida `[[TZ]]`; Mini App `/me.user.timezone`. Toshkentda QOLGANLAR (ataylab): umumiy cron (digest 09:00, hisobot, tozalash), kunlik bonus sanasi, kanal tahlili soatlari. Hujjat `docs/TIMEZONES.md`; test `tests/user_timezone_test.py`, `miniapp/src/timezone.test.ts`.
- **🌍 Mintaqaga qarab narx (TILGA BOG'LIQ EMAS):** hamma uchun standart — dollar/Telegram Stars, O'zbekiston narxidan `INTL_PRICE_MULTIPLIER`=1,7 baravar qimmat (PRO 1 oy $3.90/195★, ULTRA 1 oy $9.40/470★; Stars 5 ga yaxlitlangan; `STARS_PRICE_*` env — ASOS qiymat). So'm (karta/Payme) faqat tasdiqlangan O'zbekiston foydalanuvchisiga: «🇺🇿 So'mda to'lash» -> o'z kontakti (+998 + 9 raqam, `contact.user_id == o'zi`) -> `users.uz_verified` (raqam saqlanmaydi) yoki avval mahalliy to'lagan mijoz. `users.pay_region` — faqat ko'rinish tanlovi. Kod: `config.py`, `handlers/subscription.py` (`_user_region`, `_ask_uz_verification`, `uz_contact_callback`, `_show_local_card_payment` darvozasi), `repositories/users_repository.py` (`get_pay_region`, `verify_uz_phone`, `is_uz_eligible`); Mini App `/me.pay_region` + `periods[].usd`. Testlar: `regional_pricing_test`, `regional_pricing_db_test` (real PG); hujjat `docs/PLANS.md`.
- **CI: Python 3.11!** f-string ichida bir xil turdagi qo'shtirnoq (`f"{d["k"]}"`) 3.11 da SyntaxError (lokal 3.13 da o'tadi). Push oldidan: `python3.11 -c "import ast,glob;[ast.parse(open(f).read()) for f in glob.glob('**/*.py',recursive=True)]"`.

- **Yuborish tezligi va sig'im (yangi):** scheduler tick'da navbat bo'shaguncha paket-paket oladi (`SEND_MAX_ROUNDS`=30, har paket `POST_BATCH_SIZE`=100) va turli kanallarga `SEND_CONCURRENCY`=4 parallel yuboradi (bitta kanalga ketma-ket); oldin 100 post/daqiqa edi. Lokal o'lchovlar, zaxira nusxa va cheklovlar — `docs/OPERATIONS.md`; test `tests/scheduler_concurrency_test.py`. Mini App: admin/birja bo'laklari `React.lazy`, «Postni rejalashtirish» paneli dock ustida (`wow.css`).

- **Oddiy post paneli (ixcham) va rost holat:** preview ostida faqat 5 tugma (Hozir yuborish · Vaqt belgilash · ⚙️ Qo'shimcha · Tahrirlash · Bekor); reaksiya, havolali tugma, 🗑 24 soatlik e'lon (BELGI — vaqt keyin tanlanadi), takror va yuborish sozlamalari `⚙️ Qo'shimcha` ichida (`keyboards/inline.py:get_manual_compact_panel/get_manual_more_panel`). «Hozir yuborish» `scheduler.deliver_due_posts_now` bilan darhol yuboradi va natijani aytadi: yuborildi / navbatda / chiqmadi (`manual_post._deliver_now_and_report`). Havola: `@kanal`, `t.me/..`, `sayt.uz` qabul. Bepul nishon: matn Telegram limitiga to'lgan bo'lsa QO'YILMAYDI (`apply_post_watermark(limit=)`). Rejalashtirilgan ro'yxati: har post BITTA qator, amallar post ichida (`handlers/queue.py`). Qo'shilganini shu yerning o'zida olib tashlash (`✅` belgi + «🗑 Havolani o'chir» / «🗑 Reaksiya o'chir»); reaksiya ekranida «✅ Saqlash» (davom) va «◀️ Orqaga» (o'zgarishlarni bekor qiladi); matn kutiladigan bosqichlarda inline «◀️ Orqaga» postni yo'qotmaydi. Test: `tests/manual_post_ux_fixes_test.py`.
- **🧭 Aqlli qabul (AI bekorga ishlamaydi):** dialogdan TASHQARI kelgan matn (≥8 belgi, ≥2 so'z) / rasm / video / hujjat / albom uchun bot AI'ni O'ZI ishga tushirmaydi (oldin rasmga darhol Vision ketardi). «Bu bilan nima qilamiz?» taklifi: `📝 Post qilish` (o'zgarishsiz oddiy post preview'i), `✨ AI` (matn → Magic Post uslubi, rasm → Vision; faqat bosilganda, kredit uslub tanlanganda), `❌ Yopish`. Video/hujjat/albomda AI tugmasi yo'q. Qisqa javoblar («ha», «???», /buyruq) eski fallback'da qoladi. `/ai` + rasm — aniq buyruq, Vision darhol. Kod: `handlers/smart_intake.py`, `manual_post.manual_post_from_snapshot`, `content_creation.open_magic_style_menu`; matnlar `translations/content_menu.py` (`in_*`); test `tests/smart_intake_test.py`. AI promptiga `[QUALITY]` bloki qo'shildi (`services/ai/engine/prompts.py`: aynan so'ralganini yoz, kirish so'zi/izohsiz, faktlarni o'zgartirma).
- **📆 Oylik/haftalik takrorlash + raqamli kun + Mini App'da davom etish:** yangi tur `monthly` (`recurrence_day` = oyning kuni; oyda yo'q bo'lsa oxirgi kun; `services/recurrence.py`, `scheduler.calculate_next_time`, Mini App serveri `parse_recurrence_input`). Tabiiy til (AI'siz): «har oyning 15-kuni 10:00», «25-kuni 18:00», «25 oktabr 18:00», «haftasiga bir juma 10:00» (`services/schedule_nlp.py`: `_MONTHLY`, `_once_on_day`, `parse_day_number_once`; `utils/helpers.parse_future_time` endi «oktabr/sentabr» va inglizcha oylarni ham biladi). Botda oddiy post: «🔄 Takroriy e'lon» -> [Har kuni][Haftada bir][Oyda bir] yoki yozish (`manual_post._parse_repeat_text/_apply_repeat`, `UD_REPEAT_REC`); Mini App: Takrorlashda «Oyda bir marta». Oddiy post preview'ida Mini App yoqilgan bo'lsa «📱 Mini App'da» tugmasi: post (matn/media/albom/tugma/reaksiya) qoralamaga yoziladi va Mini App AYNAN shuni ochadi (`manual_post._sync_miniapp_draft`), yuborilgach/bekor qilingach qoralama o'chadi. Test `tests/monthly_and_miniapp_continue_test.py`, `miniapp/src/pages/recurrence.test.ts`.
- **Chet eldagi foydalanuvchi (post chiqmadi):** scheduler har zona/mamlakat uchun to'g'ri yetkazishi real PG'da tekshirilgan (`tests/foreign_user_delivery_test.py`, `FOREIGN_TEST_DATABASE_URL`). Haqiqiy xavf — zona tanlanmagan chet ellik vaqtni Toshkent bo'yicha kiritib qo'yishi: vaqt belgilanganda `handlers/timezone_flow.tz_hint` zona va `/timezone` ni eslatadi (Telegram tili o'zbekcha bo'lmasa). «Hozir yuborish» chiqmasa/navbatda qolsa endi aniq SABAB ham aytiladi (bot admin emas / format / tarmoq; `db.get_post_last_error` + `scheduler._problem_reason_key`).

- **🎁 Admin: promo ro'yxati va buyruqlar:** `/promos` (barcha kodlar: ishlatilgan/qolgan/holat), `/promo KOD` (tafsilot + kim ishlatgani), `/promo_off|on KOD`, `/admin_help` (barcha admin buyruqlari); panelda Promo-kod ekranida «📋 Kodlar», Monitoring ichida «📖 Buyruqlar» (`handlers/admin_promos.py`, `PromoService.list_promos/promo_totals/recent_redemptions/set_promo_active`). Mini App super admin rejimida yangi «Boshqaruv» tabi: Promo-kodlar (ro'yxat, yaratish, o'chirish/yoqish), Tarif berish, Tizim (holat, funksiyalar, audit), Rollar (faqat OWNER); API `miniapp_api/admin.py` (`/admin/promos|grant|audit|features|health|roles`, har biri RBAC). Test `tests/admin_promos_test.py` (real PG: `MINIAPP_TEST_DATABASE_URL`), `miniapp/src/admin.test.tsx`. Broadcast va economics hali faqat botda.

- **👥 Jamoa va rol (yangi):** PRO = bitta odam hamma kanalni boshqaradi; ULTRA = egasi + 2 yordamchi (`ULTRA_TEAM_SEATS`, jami 3 akkaunt, narx bir xil; tarif kartasida «akkauntga ≈ narx»). Rol tanlash ekrani OLIB TASHLANGAN (QAYTARMANG): Mini App Men → Jamoa va rol → «Yordamchi qo'shish»: @username/ID qidiruv (`GET /team/people`, faqat username prefiksi/ID) yoki «Kontaktlardan tanlash» (bot `request_users`, `?start=go_team`) → Telegram adminlariga o'xshash huquq tugmalari → `POST /team/invites {user_id,...}` darhol qo'shadi va yordamchiga bot xabar yuboradi (`services/team_invites.add_helper`, kuniga 10 ta chegara). Havola (`/start team_<token>`) — botdan foydalanmaydiganlar uchun. Botda Sozlamalar hub'i 6 tugma 2+2+2 — «👥 Jamoa va rol», `/team`. Yordamchi bir martalik havola (`/start team_<token>`, token hash; bir yoki bir nechta kanal) bilan qo'shiladi va egasi HAR biriga ALOHIDA RUXSAT beradi (`channel_members.perms`: create/edit/reschedule/delete/send_now/analytics/ai; shablonlar Hammasi (standart)/Muharrir/Rejalovchi/Tahlilchi/Faqat ko'rish). Ish joyi Mini App'da: `X-Workspace`, server ruxsat etilgan kanal va ruxsatni tekshiradi; post EGASI nomidan, limit/AI egasidan; media qoralama yordamchida. Bot: yordamchi media/matn yuborsa qoralama + Mini App (egasi ish joyi) (`manual_post._helper_handoff`). Kod: `services/team_invites.py`, `miniapp_api/{workspace,team}.py`, `handlers/team_ui.py`, `miniapp/src/pages/TeamScreen.tsx`. Batafsil `docs/TEAM.md`; testlar `team_invites_test`, `miniapp_team_test` (real PG), `team_ui_test`, `miniapp/src/team.test.tsx`.

- **Audit tuzatishlari:** AUDIT-001/002/003/004/005/009/010/011/013/014 + P3 (qarang `docs/AUDIT_OPEN_RISKS.md` — tuzatilganlar (recurring 'yuborildi'+qayta rejalash endi bitta tranzaksiya) va ATAYLAB qoldirilgan qarorlar: 006 Stars refund, 007 chek takrori, 015 global AI budget; 008 qisman (recovery'da kanal tekshiruvi, dublikat to'liq yo'qolmagan); 002: `DELIVERY_CARRY_ATTEMPTS` sukut yoqilgan). Regression testlar `run_tests.sh` oxirida (`scheduler_*`, `subscription_downgrade_race`, `stars_rejected_payment`, `team_i18n`, ...).

## Bilish kerak

- `/start` yangi foydalanuvchilarni taklif kodi yoki admin tasdig'isiz ro'yxatdan o'tkazadi.
- Bepul tarifda kanal postining BOSHIGA `🤖 @BOT_USERNAME\n\n` qo'shiladi (`utils/helpers.py`:
  `apply_post_watermark`; limit matnni faqat OXIRIDAN kesadi, shuning uchun nishon yo'qolmaydi). PRO/ULTRA/enterprise/admin — toza.
  Hamma yuborish yo'lida: rejalangan post, Post Enhancer, Magic/Score/Voice Post (`_magic_deliver_one(user_id=)`), Rasm->Post, tozalagich preview.
  Kafolat testi: `tests/release_readiness_audit_test.py`.
- Hostingga va production bazaga kirish yo'q; tezlik o'lchovlari faqat lokal.
- Bu konteynerda fon PostgreSQL ba'zan to'xtaydi — test oldidan qayta ishga tushir.
- Real-DB testlar (`refactor_step5_test.py`) toza bazani kutadi: qayta yugurishdan
  oldin test bazasini qayta yarat. `BOT_TOKEN=1:x` bilan
  `production_hardening_and_concurrency_test.py` 1 ta tekshiruvda yiqiladi (token
  juda qisqa, scrubber ro'yxatga olmaydi) — `run_tests.sh` ni BOT_TOKEN'siz yugurt.

## Keyingi ishlar (ustuvorlik bo'yicha)

1. PR #231 (Mini App + audit) ni egasi merge qiladi; deploy'dan keyin «Sekin javob» loglarini va Mini App'ni haqiqiy Telegram'da tekshirish.
2. ~~Umumiy kunlik AI xarajat chegarasi (`AI_GLOBAL_DAILY_USD`)~~ — qilindi;
   production'da qiymatni egasi belgilaydi (sukut 0 = o'chiq).
3. ~~Tozalagich: albom (bir nechta rasm) qo'llab-quvvatlash~~ — qilindi
   (`services/media_group_collector.py`, 1 s debounce; `tests/media_group_album_test.py`).
4. Katta fayllarni bo'lish: `utils/ai_agent.py` (~4,9k qator), `handlers/__init__.py` (~2,6k).
5. Takrorlanuvchi menyu testlarini birlashtirish; eski `get_content_creation_keyboard`
   faqat testlarda qolgan.

- **Admin/Mini App tartibga solish:** super admin paneli 4 bo'lim (Umumiy · Reklama · Birja · Boshqaruv): «Reklama» ichida avval Majburiy obuna, keyin Kanal postlari / Bot javoblari reklamalari. Promo-kodni butunlay o'chirish: Mini App Boshqaruv -> kod -> «Butunlay o'chirish», botda `/promo_del KOD` (tasdiq: `... ok`); tarixi ketadi, foydalanuvchi olgan tarif saqlanadi (`PromoService.delete_promo`). Promo FAQAT pro/ultra beradi (noma'lum tarifli eski kod tarifni o'zgartirmaydi); AI ball (kredit) berish tarifga tegmaydi (test `admin_promos_test`). Men sahifasi: ixcham profil kartasi, bo'limlar Hisob / Sozlamalar / Limitlar / Ilova. Birja: ixcham ro'yxat, «Mahalliy/Xalqaro» belgisi (`docs/AD_MARKET.md`).
