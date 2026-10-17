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

- **Bot <-> Mini App bog'lanishi:** Mini App yoqilgan bo'lsa bot «📱 Mini App» web_app tugmasini ko'rsatadi: Sozlamalar (tab=me), Rejalashtirilgan ro'yxat (tab=schedule), Tahlil (tab=me), post tasdiqlash kartasi (qoralama), `/app` va `/miniapp` buyrug'i; Mini App `?tab=home|post|schedule|me` ni o'qiydi (boshqa qiymat e'tiborsiz). O'chiq bo'lsa bot ekranlari o'zgarmaydi. Kod: `miniapp_api/menu.py` (`miniapp_tab_url`, `miniapp_button`, `with_miniapp_row`); test: `tests/miniapp_bot_links_test.py`. Mini App -> bot: «Botni ochish» (oddiy havola; `?start=` yo'q — xavfsizlik testi). To'lov, referal, autopilot, kontent-reja, jamoa — faqat botda (ataylab).

- **Kuniga ikki vaqt (`twice`):** bitta post ertalab va kechqurun chiqadi: `recurrence_type='twice'`, `recurrence_time` = erta vaqt, `recurrence_day` = kech vaqt (kun boshidan daqiqa) — sxema o'zgarmagan (`services/recurrence.py`: `twice_times`, `next_twice_occurrence`). Rejalash matni: «har kuni ertalab 9 va kechqurun 18:30 da» (`schedule_nlp.extract_two_times`); Mini App: `time2` (HH:MM), takrorlash tanlovida «kuniga 2 marta».
- **Mini App post tahrirlash:** `PATCH /posts/{id}` — matn, vaqt, tugma, takrorlanuvchida kun vaqtlari; `GET/POST/DELETE /posts/{id}/media` (ro'yxat rasmi, almashtirish, olib tashlash; rasm klientda siqiladi, ro'yxatda lazy + 3 parallel + server LRU kesh). Testlar: `tests/miniapp_post_edit_test.py`, `miniapp/src/edit.test.tsx`.

- **Yuklash tezligi:** `index.html` da `#boot` yuklash ekrani (birinchi kadrdan ilova tayyor bo'lguncha BITTA animatsiya; `src/boot.ts:hideBoot`), Telegram SDK `defer`; build `scripts/compress-dist.mjs` bilan `.br`/`.gz` yaratadi (aiohttp o'zi beradi: JS ~350 KB -> ~90 KB).
- **Profil (Men):** qatorlar Tarif / Til / Kanallarim alohida ekranlarda (`PlansScreen`: davr 1/3/6/12 oy, narx, Stars, tejam, limitlar; `LanguageScreen`; `ChannelsScreen`); `/me` `tiers.{free,pro,ultra}.periods`.

- **Mini App dizayni («vau» qatlami):** `miniapp/src/styles/wow.css` (aurora fon, suzuvchi pastki panel, kirish animatsiyalari, `CountUp`, `haptic`). Mini App -> bot deep-link ruxsat ro'yxati: `go_plans|go_settings|go_help|go_channels|go_invite` (`handlers/start.py:MINIAPP_GO_TARGETS` va `miniapp/src/telegram.ts:BOT_SECTIONS` AYNAN bir xil bo'lishi `tests/miniapp_navigation_test.py` da tekshiriladi). Bosh sahifada «Botdagi imkoniyatlar».

- **Imzo/tozalagich tugmalari botdan OLIB TASHLANDI** (egasi talabi): Sozlamalar hub'i endi 5 tugma (2+2+1), ☰ menyuda va ro'yxatda `/cleaner` yo'q. Ichki mantiq (`handlers/post_cleaner_flow.py`, `services/post_cleaner.py`) kodda qolgan — foydalanuvchi interfeysisiz; QAYTARMANG.
- **Mini App -> bot:** `openBot` chatni ochgach Mini App'ni yopadi (`telegram.ts`), shunda foydalanuvchi botda qoladi.
- **Bot /start animatsiyasi OLIB TASHLANDI** (egasi: 1 soniya ko'rinib yo'qolardi va /start'ni sekinlashtirardi). Qaytarmang.

- **Audit tuzatishlari:** AUDIT-001/002/003/004/005/009/010/011/013/014 + P3 (qarang `docs/AUDIT_OPEN_RISKS.md` — tuzatilganlar (recurring 'yuborildi'+qayta rejalash endi bitta tranzaksiya) va ATAYLAB qoldirilgan qarorlar: 006 Stars refund, 007 chek takrori, 015 global AI budget; 008 qisman (recovery'da kanal tekshiruvi, dublikat to'liq yo'qolmagan); 002: `DELIVERY_CARRY_ATTEMPTS` sukut yoqilgan). Regression testlar `run_tests.sh` oxirida (`scheduler_*`, `subscription_downgrade_race`, `stars_rejected_payment`, `team_i18n`, ...).

## Bilish kerak

- `/start` yangi foydalanuvchilarni taklif kodi yoki admin tasdig'isiz ro'yxatdan o'tkazadi.
- Bepul tarifda kanal postining OXIRIGA `\n\n🤖 @BOT_USERNAME` qo'shiladi (`utils/helpers.py`:
  `apply_post_watermark`; limit kesishidan KEYIN `compose_post_text(footer=...)`). PRO/admin — toza.
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
