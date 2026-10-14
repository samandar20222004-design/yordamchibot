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

## 📱 Mini App (yangi, `MINIAPP_ENABLED=0` — sukut bo'yicha O'CHIQ)

Vite + React + TS frontend `miniapp/`, backend qatlami `telegram_bot/miniapp_api/` (o'qish: `/api/v1/health|me|channels|scheduled-posts|posts/{id}`;
yozish: `POST/PATCH/DELETE /posts`, `PATCH /me/settings`, `POST /ai/generate`; `/app/*` statik; yuborishni bot scheduler'i bajaradi). Batafsil, xavfsizlik qarorlari va
sozlamalar — `miniapp/README.md`. Testlar: `tests/miniapp_*_test.py` (+ `cd miniapp && npm test`).

- **Bot -> Mini App qoralama (PostBot uslubi):** Mini App yoqilgan bo'lsa botdagi post tasdiqlash kartasida «📱 Mini App'da» (web_app) tugmasi; post `miniapp_drafts` ga yoziladi (bitta joriy qoralama, 48 soat). Mini App qoralama bilan ochilsa to'g'ridan-to'g'ri tahrirlagichga tushadi (format paneli, Telegram ko'rinishi, tugma, tez vaqt). Kod: `miniapp_api/drafts.py`, `handlers/new_post.py:_save_miniapp_draft`; test: `tests/miniapp_draft_test.py`, `miniapp/src/draft.test.tsx`.

- **Audit tuzatishlari:** AUDIT-001/002/003/004/005/009/010/011/013/014 + P3 (qarang `docs/AUDIT_OPEN_RISKS.md` — tuzatilganlar va ATAYLAB qoldirilgan qarorlar: 002 attempt_count, 006 Stars refund, 007 chek takrori, 008 sent-journal, 015 global AI budget). Regression testlar `run_tests.sh` oxirida (`scheduler_*`, `subscription_downgrade_race`, `stars_rejected_payment`, `team_i18n`, ...).

## Bilish kerak

- `BETA_INVITE_ONLY` sukut bo'yicha `true` — yangi foydalanuvchilar taklif kodisiz
  kira olmaydi. Production'da qiymatni egasi belgilaydi.
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
