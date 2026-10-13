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
Oxirgi natija: ~16 970 `[OK]`, 0 `[FAIL]`, 6 `[SKIP]` (pgserver/redis yo'q).

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
- **Umumiy kunlik AI chegarasi:** `AI_GLOBAL_DAILY_USD` (USD, barcha foydalanuvchilar,
  UTC kun; 0 = o'chiq, sukut). `BudgetGuard.acquire` foydalanuvchi limitlaridan keyin
  tekshiradi: bugungi sarf (xotira ledger va DB `get_ai_global_cost_usd`, 30 s kesh) +
  barcha bronlar + yangi so'rov. Oshsa — `global_daily_usd`, provayder chaqirilmaydi,
  foydalanuvchiga «xizmat limiti» xabari (PRO taklif qilinmaydi), logda kuniga 1 WARNING.
  Test: `tests/ai_cost_protection_test.py` (TEST 5b).

## Bilish kerak

- `BETA_INVITE_ONLY` sukut bo'yicha `true` — yangi foydalanuvchilar taklif kodisiz
  kira olmaydi. Production'da qiymatni egasi belgilaydi.
- Bepul tarifda kanal postining boshiga `@BOT_USERNAME` qo'shiladi (mavjud qoida).
- Hostingga va production bazaga kirish yo'q; tezlik o'lchovlari faqat lokal.
- Bu konteynerda fon PostgreSQL ba'zan to'xtaydi — test oldidan qayta ishga tushir.
- Real-DB testlar (`refactor_step5_test.py`) toza bazani kutadi: qayta yugurishdan
  oldin test bazasini qayta yarat. `BOT_TOKEN=1:x` bilan
  `production_hardening_and_concurrency_test.py` 1 ta tekshiruvda yiqiladi (token
  juda qisqa, scrubber ro'yxatga olmaydi) — `run_tests.sh` ni BOT_TOKEN'siz yugurt.

## Keyingi ishlar (ustuvorlik bo'yicha)

1. PR #216 ni egasi merge qiladi; deploy'dan keyin «Sekin javob» loglarini ko'rish.
2. ~~Umumiy kunlik AI xarajat chegarasi (`AI_GLOBAL_DAILY_USD`)~~ — qilindi;
   production'da qiymatni egasi belgilaydi (sukut 0 = o'chiq).
3. Tozalagich: albom (bir nechta rasm) qo'llab-quvvatlash.
4. Katta fayllarni bo'lish: `utils/ai_agent.py` (~4,9k qator), `handlers/__init__.py` (~2,6k).
5. Takrorlanuvchi menyu testlarini birlashtirish; eski `get_content_creation_keyboard`
   faqat testlarda qolgan.
